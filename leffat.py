import os
import json
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import requests
from playwright.sync_api import sync_playwright
from collections import defaultdict

OMDB_API_KEY = os.getenv('OMDB_API_KEY', 'SINUN_OMDB_AVAIMESI_TÄHÄN')

def get_kinoon_movies(page):
    """Hakee Kinoon.fi:n elokuvat."""
    print("Haetaan Kinoon.fi näytöksiä (selainmoottorilla)...")
    movies = []
    seen_titles = set()
    
    try:
        page.goto("https://kinoon.fi/helsinki/elokuvat-ja-esitysajat", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('[data-film-card-id]', timeout=15000)
        
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        film_cards = soup.find_all('div', attrs={'data-film-card-id': True})
        
        for card in film_cards:
            try:
                link = card.find('a')
                if not link:
                    continue
                
                url = "https://kinoon.fi" + link.get('href', '')
                img = card.find('img', alt=True)
                if not img:
                    continue
                    
                title = img['alt'].strip()
                
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    
                    poster_url = img.get('src', '')
                    if poster_url and not poster_url.startswith('http'):
                        poster_url = "https://kinoon.fi" + poster_url
                    
                    movies.append({
                        "title": title,
                        "search_title": title,
                        "url": url,
                        "source": "Kinoon.fi",
                        "poster_url": poster_url if poster_url else None,
                        "showtimes": []
                    })
                    
            except Exception as e:
                continue
                
    except Exception as e:
        print(f"Virhe Kinoon.fi datan haussa: {e}")
        
    print(f"Löydettiin {len(movies)} elokuvaa Kinoon.fi:stä")
    return movies

def get_kinot_movies(page):
    """Hakee Kinot.fi näytökset."""
    print("Haetaan Kinot.fi näytöksiä (selainmoottorilla)...")
    movies = []
    
    try:
        page.goto("https://www.kinot.fi/", wait_until="networkidle", timeout=30000)
        page.wait_for_selector('.show-item', timeout=15000)
        
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        show_items = soup.find_all('div', class_='show-item')
        
        for item in show_items:
            try:
                link_elem = item.find('a')
                url = "https://www.kinot.fi" + link_elem['href'] if link_elem and link_elem.has_attr('href') else ""
                
                text_wrapper = item.find('div', class_='text-wrapper')
                if not text_wrapper:
                    continue
                    
                texts = list(text_wrapper.stripped_strings)
                
                if len(texts) >= 3:
                    title = texts[0]
                    time_str = texts[1]
                    theatre = texts[2].replace('>', '').strip()
                    
                    search_title = title
                    if ": " in title:
                        search_title = title.split(": ")[-1]
                        
                    movies.append({
                        "title": title,
                        "search_title": search_title,
                        "url": url,
                        "source": "Kinot.fi",
                        "poster_url": None,
                        "showtimes": [{
                            "theatre": theatre,
                            "time": time_str
                        }]
                    })
            except Exception:
                continue
        
        print(f"Löydettiin {len(movies)} näytöstä Kinot.fi:stä")
                
    except Exception as e:
        print(f"Virhe Kinot.fi datan haussa: {e}")
        
    return movies

def merge_duplicates(movie_list):
    """Yhdistää duplikaatit samaan elokuvaan ja kerää esitysajat."""
    print("\nYhdistetään duplikaatit...")
    merged = {}
    
    for movie in movie_list:
        # Normalisoidaan avain
        key = movie["search_title"].lower().strip()
        key = ' '.join(key.split())
        
        # Poistetaan vuosiluvut suluista esim. "Movie (2024)" -> "movie"
        key = re.sub(r'\s*\(\d{4}\)\s*', '', key)
        
        if key in merged:
            # Yhdistetään esitysajat
            merged[key]["showtimes"].extend(movie["showtimes"])
            
            # Säilytetään parempi poster
            if not merged[key]["poster_url"] and movie["poster_url"]:
                merged[key]["poster_url"] = movie["poster_url"]
                
            # Säilytetään parempi URL
            if not merged[key].get("url") and movie.get("url"):
                merged[key]["url"] = movie["url"]
        else:
            merged[key] = movie
    
    result = list(merged.values())
    removed = len(movie_list) - len(result)
    print(f"Duplikaattien poiston jälkeen: {len(result)} uniikkia elokuvaa ({removed} duplikaattia poistettu)")
    return result

def format_showtimes(movie):
    """Ryhmittelee esitysajat teattereittain."""
    by_theatre = defaultdict(list)
    
    for show in movie.get("showtimes", []):
        theatre = show.get("theatre", "Tuntematon teatteri")
        time = show.get("time", "")
        if time:
            by_theatre[theatre].append(time)
    
    return [
        {"theatre": theatre, "times": times}
        for theatre, times in by_theatre.items()
    ]

def fetch_omdb_data(movie_list):
    """Hakee kattavat tiedot OMDb:stä."""
    print("\nHaetaan lisätietoja OMDb:stä...")
    
    if OMDB_API_KEY == "SINUN_OMDB_AVAIMESI_TÄHÄN":
        print("⚠️  OMDb API-avain puuttuu, ohitetaan lisätietojen haku.")
        print("   Hanki avain: http://www.omdbapi.com/apikey.aspx")
        return
    
    cache = {}
    
    for i, movie in enumerate(movie_list, 1):
        search_title = movie["search_title"]
        
        if search_title in cache:
            movie.update(cache[search_title])
            continue
        
        try:
            url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={search_title}&plot=short"
            res = requests.get(url, timeout=5)
            data = res.json()
            
            if data.get("Response") == "True":
                # Rotten Tomatoes ja Metacritic
                rt_score = None
                metacritic_score = None
                
                for rating in data.get("Ratings", []):
                    if rating["Source"] == "Rotten Tomatoes":
                        rt_score = rating["Value"]
                    elif rating["Source"] == "Metacritic":
                        metacritic_score = rating["Value"]
                
                omdb_info = {
                    "imdb_rating": data.get("imdbRating"),
                    "imdb_votes": data.get("imdbVotes"),
                    "rt_rating": rt_score,
                    "metacritic": metacritic_score,
                    "year": data.get("Year"),
                    "rated": data.get("Rated"),
                    "runtime": data.get("Runtime"),
                    "genre": data.get("Genre"),
                    "director": data.get("Director"),
                    "actors": data.get("Actors"),
                    "plot": data.get("Plot"),
                    "language": data.get("Language"),
                    "country": data.get("Country"),
                    "awards": data.get("Awards"),
                    "box_office": data.get("BoxOffice")
                }
                
                # Käytä OMDb:n julistetta vain jos ei ole jo
                if not movie.get("poster_url"):
                    poster = data.get("Poster")
                    if poster and poster != "N/A":
                        omdb_info["poster_url"] = poster
                
                cache[search_title] = omdb_info
                movie.update(omdb_info)
                
                ratings_str = f"IMDb: {omdb_info.get('imdb_rating', 'N/A')}"
                if rt_score:
                    ratings_str += f", RT: {rt_score}"
                print(f"  [{i}/{len(movie_list)}] {search_title}: {ratings_str}")
                
        except Exception as e:
            print(f"  [{i}/{len(movie_list)}] {search_title}: Virhe")

def main():
    print("🎬 Elokuvahaku käynnistyy...\n")
    print("Käynnistetään selainmoottori (Playwright)...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        kinoon_data = get_kinoon_movies(page)
        kinot_data = get_kinot_movies(page)
        
        browser.close()
    
    all_movies = kinoon_data + kinot_data
    
    if not all_movies:
        print("\n❌ Yhtään elokuvaa ei löydetty.")
        return
    
    # Yhdistetään duplikaatit
    unique_movies = merge_duplicates(all_movies)
    
    print(f"\n📊 Yhteensä {len(unique_movies)} uniikkia elokuvaa")
    
    fetch_omdb_data(unique_movies)
    
    # Muotoillaan esitysajat
    for movie in unique_movies:
        movie["showtimes"] = format_showtimes(movie)
    
    # Järjestetään IMDb-arvosanan mukaan
    unique_movies.sort(
        key=lambda x: (
            float(x.get("imdb_rating", 0)) if x.get("imdb_rating") and x.get("imdb_rating") != "N/A" else -1.0
        ), 
        reverse=True
    )
    
    output_filename = "leffat.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(unique_movies, f, ensure_ascii=False, indent=2)
    
    # Tulostetaan TOP 5 (nyt ilman duplikaatteja!)
    print("\n🏆 TOP 5 ELOKUVAA (IMDb):")
    count = 0
    for movie in unique_movies:
        rating = movie.get('imdb_rating')
        if rating and rating != 'N/A':
            rt = movie.get('rt_rating', 'N/A')
            print(f"  {count+1}. {movie['title']}")
            print(f"     IMDb: {rating} | RT: {rt}")
            count += 1
            if count >= 5:
                break
    
    print(f"\n✅ Valmis! Tiedot tallennettu: {output_filename}")
    print(f"📍 Elokuvat sisältävät nyt teatterikohtaiset esitysajat")

if __name__ == "__main__":
    main()

import os
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import requests
from playwright.sync_api import sync_playwright
from collections import defaultdict

OMDB_API_KEY = os.getenv('OMDB_API_KEY', 'SINUN_OMDB_AVAIMESI_TÄHÄN')

def get_kinoon_movies(page):
    """Hakee Kinoon.fi:n elokuvat (korvaa Finnkinon)."""
    print("Haetaan Kinoon.fi näytöksiä (selainmoottorilla)...")
    movies = []
    seen_titles = set()
    
    try:
        # Kinoon.fi:n pääsivu näyttää kaikki ohjelmistossa olevat elokuvat
        page.goto("https://kinoon.fi/helsinki/elokuvat-ja-esitysajat", wait_until="domcontentloaded", timeout=30000)
        
        # Odotetaan että elokuvakortit latautuvat
        page.wait_for_selector('[data-film-card-id]', timeout=15000)
        
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Etsitään kaikki elokuvakortit
        film_cards = soup.find_all('div', attrs={'data-film-card-id': True})
        
        for card in film_cards:
            try:
                # Haetaan linkki ja otsikko
                link = card.find('a')
                if not link:
                    continue
                
                url = "https://kinoon.fi" + link.get('href', '')
                
                # Otsikko on img alt-tekstissä
                img = card.find('img', alt=True)
                if not img:
                    continue
                    
                title = img['alt'].strip()
                
                # Vältetään duplikaatit
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    
                    # Julisteen URL
                    poster_url = img.get('src', '')
                    if poster_url and not poster_url.startswith('http'):
                        poster_url = "https://kinoon.fi" + poster_url
                    
                    # Etsitään teatteritieto (jos näkyy kortilla)
                    theatre_info = "Kinoon.fi (useita teattereita)"
                    
                    movies.append({
                        "title": title,
                        "search_title": title,
                        "time": "Katso ajat sivuilta",
                        "theatre": theatre_info,
                        "url": url,
                        "source": "Kinoon.fi",
                        "imdb_rating": None,
                        "rt_rating": None,
                        "poster_url": poster_url if poster_url else None
                    })
                    
            except Exception as e:
                print(f"Virhe kortin käsittelyssä: {e}")
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
                        "time": time_str,
                        "theatre": theatre,
                        "url": url,
                        "source": "Kinot.fi",
                        "imdb_rating": None,
                        "rt_rating": None,
                        "poster_url": None
                    })
            except Exception:
                continue
        
        print(f"Löydettiin {len(movies)} näytöstä Kinot.fi:stä")
                
    except Exception as e:
        print(f"Virhe Kinot.fi datan haussa: {e}")
        
    return movies

def fetch_omdb_data(movie_list):
    """Hakee arvosanat ja julisteet OMDb:stä."""
    print("Haetaan julisteita ja arvosanoja OMDb:stä...")
    cache = {}
    
    if OMDB_API_KEY == "SINUN_OMDB_AVAIMESI_TÄHÄN":
        print("HUOM: OMDb API-avain puuttuu, ohitetaan lisätietojen haku.")
        return
    
    for i, movie in enumerate(movie_list, 1):
        search_title = movie["search_title"]
        
        if search_title in cache:
            movie.update(cache[search_title])
            continue
        
        try:
            url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={search_title}"
            res = requests.get(url, timeout=5)
            data = res.json()
            
            if data.get("Response") == "True":
                rt_score = None
                for rating in data.get("Ratings", []):
                    if rating["Source"] == "Rotten Tomatoes":
                        rt_score = rating["Value"]
                        break
                
                omdb_info = {
                    "imdb_rating": data.get("imdbRating"),
                    "rt_rating": rt_score,
                }
                
                # Käytä OMDb:n julistetta vain jos Kinoon.fi:stä ei tullut
                if not movie.get("poster_url"):
                    poster = data.get("Poster")
                    if poster and poster != "N/A":
                        omdb_info["poster_url"] = poster
                
                cache[search_title] = omdb_info
                movie.update(omdb_info)
                
                print(f"  [{i}/{len(movie_list)}] {search_title}: IMDb {omdb_info.get('imdb_rating', 'N/A')}")
                
        except Exception as e:
            print(f"  [{i}/{len(movie_list)}] {search_title}: Virhe ({e})")

def main():
    print("🎬 Elokuvahaku käynnistyy...\n")
    print("Käynnistetään selainmoottori (Playwright)...")
    
    with sync_playwright() as p:
        # Vaihda headless=True jos et halua nähdä selainta
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        # UUSI: Kinoon.fi korvaa Finnkinon
        kinoon_data = get_kinoon_movies(page)
        
        # Säilytetään Kinot.fi
        kinot_data = get_kinot_movies(page)
        
        browser.close()
    
    all_movies = kinoon_data + kinot_data
    
    if not all_movies:
        print("\n❌ Yhtään elokuvaa ei löydetty. Tarkista nettiyhteys.")
        return
    
    print(f"\n📊 Yhteensä {len(all_movies)} elokuvaa löydetty")
    print(f"   - Kinoon.fi: {len(kinoon_data)} elokuvaa")
    print(f"   - Kinot.fi: {len(kinot_data)} näytöstä\n")
    
    fetch_omdb_data(all_movies)
    
    # Järjestetään IMDb-arvosanan mukaan
    all_movies.sort(
        key=lambda x: float(x["imdb_rating"]) if x["imdb_rating"] and x["imdb_rating"] != "N/A" else -1.0, 
        reverse=True
    )
    
    output_filename = "leffat.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(all_movies, f, ensure_ascii=False, indent=4)
    
    # Tulostetaan top 5
    print("\n🏆 TOP 5 ELOKUVAA (IMDb):")
    for i, movie in enumerate(all_movies[:5], 1):
        rating = movie.get('imdb_rating', 'N/A')
        print(f"  {i}. {movie['title']} - IMDb: {rating}")
        
    print(f"\n✅ Valmis! Tiedot tallennettu: {output_filename}")

if __name__ == "__main__":
    main()

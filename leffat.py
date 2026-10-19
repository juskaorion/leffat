import os
import json
import re
import urllib.parse
from datetime import datetime
from bs4 import BeautifulSoup
import requests
from playwright.sync_api import sync_playwright

OMDB_API_KEY = os.getenv('OMDB_API_KEY', 'SINUN_OMDB_AVAIMESI_TÄHÄN')

THEATRE_URL_MAP = {
    "Tennispalatsi": "https://www.finnkino.fi/teatterit/tennispalatsi",
    "Kinopalatsi": "https://www.finnkino.fi/teatterit/kinopalatsi",
    "Itis": "https://www.finnkino.fi/teatterit/itis",
    "Maxim": "https://www.finnkino.fi/teatterit/maxim",
    "Flamingo": "https://www.finnkino.fi/teatterit/flamingo",
    "Omena": "https://www.finnkino.fi/teatterit/omena",
    "Sello": "https://www.finnkino.fi/teatterit/sello",
    "Cinema Orion": "https://cinemaorion.fi/",
    "Orion": "https://cinemaorion.fi/",
    "Kino Regina": "https://kinoregina.fi/",
    "Regina": "https://kinoregina.fi/",
    "Kino Engel": "https://kinoengel.fi/",
    "Engel": "https://kinoengel.fi/",
    "Riviera Kallio": "https://rivierakallio.fi/",
    "Riviera Punavuori": "https://rivierakallio.fi/",
    "Riviera": "https://rivierakallio.fi/",
    "Kino Konepaja": "https://kinokonepaja.fi/",
    "BioRex Tripla": "https://biorex.fi/elokuvateatterit/helsinki-tripla/",
    "BioRex Redi": "https://biorex.fi/elokuvateatterit/helsinki-redi/",
    "BioRex Lasipalatsi": "https://biorex.fi/elokuvateatterit/helsinki-lasipalatsi/",
    "Bio Rex": "https://biorex.fi/",
    "Kino Tapiola": "https://kinotapiola.fi/",
    "Kino Töölö": "https://kinotoolo.fi/",
    "Kino K-13": "https://kino-k13.fi/",
    "Gilda": "https://www.kinogilda.fi/",
    "Korjaamo Kino": "https://korjaamo.fi/kino/",
    "Kino Laika": "https://kinolaika.fi/"
}

def resolve_theatre_url(name, direct_url=None):
    if direct_url and direct_url.startswith("http"):
        return direct_url
    for key, url in THEATRE_URL_MAP.items():
        if key.lower() in name.lower():
            return url
    return direct_url if direct_url else ""

def clean_title_for_search(title):
    """Puhdistaa nimen häiriötekijöistä OMDb-hakua varten."""
    cleaned = re.sub(r'\(.*?\)', '', title)
    cleaned = re.sub(r'\b(2D|3D|dub|dubattu|orig|kavi|sing-along|preview|ennakko)\b', '', cleaned, flags=re.IGNORECASE)
    if ":" in cleaned and any(prefix in cleaned.lower() for prefix in ["kavi", "kino", "erikoisnäytös"]):
        cleaned = cleaned.split(":")[-1]
    return cleaned.strip()

def get_kinoon_movies(page):
    print("Haetaan Kinoon.fi elokuvia...")
    movies = []
    seen_titles = set()
    
    try:
        page.goto("https://kinoon.fi/helsinki/elokuvat-ja-esitysajat", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('[data-film-card-id]', timeout=15000)
        
        soup = BeautifulSoup(page.content(), 'html.parser')
        film_cards = soup.find_all('div', attrs={'data-film-card-id': True})
        
        for card in film_cards:
            try:
                link = card.find('a')
                img = card.find('img', alt=True)
                if not link or not img:
                    continue
                    
                title = img['alt'].strip()
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    url = "https://kinoon.fi" + link.get('href', '')
                    poster_url = img.get('src', '')
                    if poster_url and not poster_url.startswith('http'):
                        poster_url = "https://kinoon.fi" + poster_url
                    
                    movies.append({
                        "title": title,
                        "search_title": title,
                        "url": url,
                        "source": "Kinoon.fi",
                        "poster_url": poster_url if poster_url else None,
                        "esityspaikat": []
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"Virhe Kinoon.fi datan haussa: {e}")
        
    return movies

def get_kinot_movies(page):
    print("Haetaan Kinot.fi elokuvia...")
    movies = []
    try:
        page.goto("https://www.kinot.fi/", wait_until="networkidle", timeout=30000)
        page.wait_for_selector('.show-item', timeout=15000)
        
        soup = BeautifulSoup(page.content(), 'html.parser')
        show_items = soup.find_all('div', class_='show-item')
        
        for item in show_items:
            try:
                link_elem = item.find('a')
                url = "https://www.kinot.fi" + link_elem['href'] if link_elem and link_elem.has_attr('href') else ""
                text_wrapper = item.find('div', class_='text-wrapper')
                if not text_wrapper: continue
                    
                texts = list(text_wrapper.stripped_strings)
                if len(texts) >= 3:
                    title = texts[0]
                    theatre_name = texts[2].replace('>', '').strip()
                    theatre_url = resolve_theatre_url(theatre_name)
                        
                    movies.append({
                        "title": title,
                        "search_title": title,
                        "url": url,
                        "source": "Kinot.fi",
                        "poster_url": None,
                        "esityspaikat": [{
                            "nimi": theatre_name,
                            "url": theatre_url,
                            "html": f'<a href="{theatre_url}" target="_blank">{theatre_name}</a>' if theatre_url else theatre_name
                        }]
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"Virhe Kinot.fi datan haussa: {e}")
        
    return movies

def get_kinoon_details(page, movie_url):
    """Hakee esityspaikat ja alkuperäisen nimen Kinoon.fi-sivulta."""
    venues = []
    original_title = None
    seen_venues = set()
    
    try:
        page.goto(movie_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1000)
        
        soup = BeautifulSoup(page.content(), 'html.parser')
        
        # 1. Esityspaikat
        showtime_divs = soup.find_all('div', class_=lambda x: x and 'flex items-center gap-3 px-3 py-3' in x)
        for div in showtime_divs:
            theatre_span = div.find('span', class_=lambda x: x and 'text-zinc-200' in x)
            if theatre_span:
                t_name = theatre_span.get_text(strip=True)
                if t_name not in seen_venues:
                    seen_venues.add(t_name)
                    t_link = resolve_theatre_url(t_name)
                    venues.append({
                        "nimi": t_name,
                        "url": t_link,
                        "html": f'<a href="{t_link}" target="_blank">{t_name}</a>' if t_link else t_name
                    })
        
        # 2. Alkuperäinen nimi (Kuvankaappauksen rakenteen mukaisesti)
        title_container = soup.find('div', class_=lambda x: x and 'fdp-reveal-title' in x)
        if title_container:
            orig_title_elem = title_container.find('p', class_=lambda x: x and 'text-sm' in x and 'text-zinc-300' in x)
            if orig_title_elem:
                original_title = orig_title_elem.get_text(strip=True)
                
    except Exception as e:
        print(f"  Virhe elokuvan lisätietojen haussa: {e}")
        
    return venues, original_title

def merge_duplicates(movie_list):
    merged = {}
    for movie in movie_list:
        key = clean_title_for_search(movie["search_title"]).lower()
        
        if key in merged:
            existing_theatres = {t["nimi"] for t in merged[key].get("esityspaikat", [])}
            for venue in movie.get("esityspaikat", []):
                if venue["nimi"] not in existing_theatres:
                    merged[key]["esityspaikat"].append(venue)
                    existing_theatres.add(venue["nimi"])
            
            if not merged[key]["poster_url"] and movie["poster_url"]:
                merged[key]["poster_url"] = movie["poster_url"]
            if not merged[key].get("url") and movie.get("url"):
                merged[key]["url"] = movie["url"]
        else:
            merged[key] = movie
            
    return list(merged.values())

def fetch_omdb_data(movie_list):
    print("\nHaetaan lisätietoja OMDb:stä...")
    if OMDB_API_KEY == "SINUN_OMDB_AVAIMESI_TÄHÄN":
        return
    cache = {}

    for i, movie in enumerate(movie_list, 1):
        raw_title = movie["search_title"]
        search_title = clean_title_for_search(raw_title)

        if search_title in cache:
            movie.update(cache[search_title])
            continue

        try:
            url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={urllib.parse.quote(search_title)}&plot=short"
            res = requests.get(url, timeout=5).json()

            if res.get("Response") == "True":
                rt_score = next((r["Value"] for r in res.get("Ratings", []) if r["Source"] == "Rotten Tomatoes"), None)
                metacritic_score = next((r["Value"] for r in res.get("Ratings", []) if r["Source"] == "Metacritic"), None)

                omdb_info = {
                    "imdb_rating": res.get("imdbRating"),
                    "imdb_votes": res.get("imdbVotes"),
                    "rt_rating": rt_score,
                    "metacritic": metacritic_score,
                    "year": res.get("Year"),
                    "runtime": res.get("Runtime"),
                    "genre": res.get("Genre"),
                    "plot": res.get("Plot")
                }
                
                # Päivitetään juliste vain jos alkuperäistä ei ole
                if not movie.get("poster_url") and res.get("Poster") and res.get("Poster") != "N/A":
                    omdb_info["poster_url"] = res.get("Poster")

                cache[search_title] = omdb_info
                movie.update(omdb_info)
                print(f"  [{i}/{len(movie_list)}] {raw_title} -> IMDb: {omdb_info.get('imdb_rating')}")
            else:
                print(f"  [{i}/{len(movie_list)}] {raw_title} -> Ei löytynyt OMDb:stä")
                
        except Exception:
            pass

def main():
    print("🎬 Elokuvahaku käynnistyy...\n")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        all_movies = get_kinoon_movies(page) + get_kinot_movies(page)
        if not all_movies:
            browser.close()
            return
            
        unique_movies = merge_duplicates(all_movies)
        print(f"\n📊 Yhteensä {len(unique_movies)} uniikkia elokuvaa. Haetaan lisätiedot sivustoilta...")
        
        # 1. Haetaan kaikille alkuperäisnimi ja teatterit ENSIN
        for i, movie in enumerate(unique_movies, 1):
            if movie.get("source") == "Kinoon.fi" and movie.get("url"):
                venues, orig_title = get_kinoon_details(page, movie["url"])
                
                # Jos alkuperäisnimi löytyi, käytetään sitä OMDb-hakusana!
                if orig_title:
                    movie["search_title"] = orig_title
                    
                existing_theatres = {t["nimi"] for t in movie.get("esityspaikat", [])}
                for venue in venues:
                    if venue["nimi"] not in existing_theatres:
                        movie["esityspaikat"].append(venue)
                        existing_theatres.add(venue["nimi"])
                        
        browser.close()
        
        # 2. Haetaan OMDb-tiedot alkuperäisnimillä
        fetch_omdb_data(unique_movies)
        
        unique_movies.sort(
            key=lambda x: float(x.get("imdb_rating", 0)) if x.get("imdb_rating") and x.get("imdb_rating") != "N/A" else -1.0, 
            reverse=True
        )
        
    paivitetty_teksti = datetime.now().strftime("päivitetty %d.%m.%Y klo %H.%M")
    
    with open("leffat.json", "w", encoding="utf-8") as f:
        json.dump({"paivitetty": paivitetty_teksti, "elokuvat": unique_movies}, f, ensure_ascii=False, indent=2)
    
    print("\n✅ Valmis!")

if __name__ == "__main__":
    main()

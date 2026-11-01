import os
import json
import re
import urllib.parse
from datetime import datetime
from bs4 import BeautifulSoup
import requests
import gzip
import csv
from playwright.sync_api import sync_playwright

OMDB_API_KEY = os.getenv('OMDB_API_KEY') 
TMDB_API_KEY = os.getenv('TMDB_API_KEY')

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
    if direct_url and direct_url.startswith("http"): return direct_url
    for key, url in THEATRE_URL_MAP.items():
        if key.lower() in name.lower(): return url
    return direct_url if direct_url else ""

def clean_title_for_search(title):
    if not title: return ""
    cleaned = re.sub(r'\(.*?\)', '', title)
    cleaned = re.sub(r'\b(2D|3D|dub|dubattu|orig|kavi|sing-along|preview|ennakko)\b', '', cleaned, flags=re.IGNORECASE)
    if ":" in cleaned and any(prefix in cleaned.lower() for prefix in ["kavi", "kino", "erikoisnäytös"]):
        cleaned = cleaned.split(":")[-1]
    return cleaned.strip()

def get_kinoon_movies(page):
    print("Haetaan Kinoon.fi elokuvia...")
    movies, seen_titles = [], set()
    try:
        page.goto("https://kinoon.fi/helsinki/elokuvat-ja-esitysajat", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_selector('[data-film-card-id]', timeout=20000)
        soup = BeautifulSoup(page.content(), 'html.parser')
        
        for card in soup.find_all('div', attrs={'data-film-card-id': True}):
            try:
                link, img = card.find('a'), card.find('img', alt=True)
                if not link or not img: continue
                title = img['alt'].strip()
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    url = "https://kinoon.fi" + link.get('href', '')
                    poster_url = img.get('src', '')
                    if poster_url and not poster_url.startswith('http'): poster_url = "https://kinoon.fi" + poster_url
                    movies.append({
                        "title": title, "search_title": title, "url": url,
                        "source": "Kinoon.fi", "poster_url": poster_url or None, "esityspaikat": []
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
        
        for item in soup.find_all('div', class_='show-item'):
            try:
                link_elem = item.find('a')
                url = "https://www.kinot.fi" + link_elem['href'] if link_elem and link_elem.has_attr('href') else ""
                text_wrapper = item.find('div', class_='text-wrapper')
                if not text_wrapper: continue
                texts = list(text_wrapper.stripped_strings)
                if len(texts) >= 3:
                    title, theatre_name = texts[0], texts[2].replace('>', '').strip()
                    theatre_url = resolve_theatre_url(theatre_name)
                    movies.append({
                        "title": title, "search_title": title, "url": url, "source": "Kinot.fi", "poster_url": None,
                        "esityspaikat": [{"nimi": theatre_name, "url": theatre_url, "html": f'<a href="{theatre_url}" target="_blank">{theatre_name}</a>' if theatre_url else theatre_name}]
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"Virhe Kinot.fi datan haussa: {e}")
    return movies

def get_kinoon_details(page, movie_url):
    venues, original_title, year, seen_venues = [], None, None, set()
    try:
        page.goto(movie_url, wait_until="domcontentloaded", timeout=15000)
        try:
            btn = page.locator('button', has_text=re.compile(r"Hyväksy|Salli|Kyllä|Accept", re.IGNORECASE)).first
            btn.wait_for(state="visible", timeout=2000)
            btn.click()
            page.wait_for_timeout(1000)
        except Exception:
            pass
        
        soup = BeautifulSoup(page.content(), 'html.parser')
        for div in soup.find_all('div', class_=lambda x: x and 'flex items-center gap-3 px-3 py-3' in x):
            theatre_span = div.find('span', class_=lambda x: x and 'text-zinc-200' in x)
            if theatre_span:
                t_name = theatre_span.get_text(strip=True)
                if t_name not in seen_venues:
                    seen_venues.add(t_name)
                    t_link = resolve_theatre_url(t_name)
                    venues.append({"nimi": t_name, "url": t_link, "html": f'<a href="{t_link}" target="_blank">{t_name}</a>' if t_link else t_name})
        
        title_container = soup.find('div', class_=lambda x: x and 'fdp-reveal-title' in x)
        if title_container:
            for sub in title_container.find_all(['span', 'p'], class_=lambda x: x and ('text-zinc-200' in x or 'text-zinc-300' in x)):
                if sub.get_text(strip=True):
                    original_title = sub.get_text(strip=True)
                    break
            year_match = re.search(r'\b(19|20)\d{2}\b', title_container.get_text())
            if year_match: year = year_match.group(0)
    except Exception:
        pass
    return venues, original_title, year

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
            if not merged[key]["poster_url"] and movie["poster_url"]: merged[key]["poster_url"] = movie["poster_url"]
            if not merged[key].get("url") and movie.get("url"): merged[key]["url"] = movie["url"]
        else:
            merged[key] = movie
    return list(merged.values())

def load_imdb_ratings():
    print("\n📥 Ladataan IMDb:n virallista arvosanatietokantaa (n. 7 MB)...")
    url = "https://datasets.imdbws.com/title.ratings.tsv.gz"
    res = requests.get(url)
    content = gzip.decompress(res.content).decode('utf-8')
    ratings = {}
    reader = csv.reader(content.splitlines(), delimiter='\t')
    next(reader) 
    for row in reader:
        if len(row) == 3:
            ratings[row[0]] = {"rating": row[1], "votes": row[2]}
    print(f"✅ Ladattu arvosanat {len(ratings):,} elokuvalle/sarjalle!")
    return ratings

def fetch_metadata_via_dataset(movie_list, ratings_db):
    print("\nHaetaan elokuvien lisätiedot API-rajapinnoista (TMDB ensin, sitten OMDb) ja arvosanat datasetistä...")
    cache = {}

    for i, movie in enumerate(movie_list, 1):
        raw_title = movie["search_title"]
        fin_title = clean_title_for_search(raw_title)
        orig_title = clean_title_for_search(movie.get("original_title", ""))
        expected_year = movie.get("year")
        
        titles_to_try = []
        if orig_title and orig_title.lower() != fin_title.lower(): titles_to_try.append(orig_title)
        titles_to_try.append(fin_title)

        cache_key = fin_title + str(expected_year)
        if cache_key in cache:
            movie.update(cache[cache_key])
            print(f"  [{i}/{len(movie_list)}] Osuma välimuistista: '{fin_title}' -> Arvosana: {movie.get('imdb_rating')}")
            continue

        updates = {}
        imdb_id = None
        id_source = ""

        # VAIHE 1: TMDB - Joustavampi haku ID:lle ja metadatalle
        for search_title in titles_to_try:
            try:
                search_params = {"api_key": TMDB_API_KEY, "query": search_title, "language": "fi-FI"}
                if expected_year: search_params["primary_release_year"] = expected_year
                
                search_res = requests.get("https://api.themoviedb.org/3/search/movie", params=search_params, timeout=5).json()
                
                if not search_res.get("results") and expected_year:
                    search_params.pop("primary_release_year", None)
                    search_res = requests.get("https://api.themoviedb.org/3/search/movie", params=search_params, timeout=5).json()

                if search_res.get("results"):
                    best_match = search_res["results"][0]
                    detail_url = f"https://api.themoviedb.org/3/movie/{best_match['id']}?api_key={TMDB_API_KEY}&language=fi-FI"
                    detail_res = requests.get(detail_url, timeout=5).json()
                    
                    imdb_id = detail_res.get("imdb_id")
                    if imdb_id:
                        id_source = "TMDB"
                    
                    updates["year"] = best_match.get("release_date", "")[:4] if best_match.get("release_date") else None
                    updates["plot"] = detail_res.get("overview") or best_match.get("overview")
                    updates["genre"] = ", ".join([g["name"] for g in detail_res.get("genres", [])])
                    updates["runtime"] = f"{detail_res.get('runtime')} min" if detail_res.get("runtime") else None
                    
                    # MUUTOS: Päivitetään kuva vain, jos elokuvalla EI OLE vielä kuvaa Kinoon.fi:stä
                    if not movie.get("poster_url") and best_match.get("poster_path"):
                        updates["poster_url"] = f"https://image.tmdb.org/t/p/w500{best_match.get('poster_path')}"
                    break 
            except Exception:
                pass

        # VAIHE 2: OMDb - Vain varasuunnitelmana, jos TMDB ei löytänyt mitään
        if not imdb_id:
            for search_title in titles_to_try:
                try:
                    params = {"apikey": OMDB_API_KEY, "t": search_title, "plot": "short"}
                    if expected_year: params["y"] = expected_year
                    res = requests.get(f"http://www.omdbapi.com/?{urllib.parse.urlencode(params)}", timeout=5).json()
                    
                    if res.get("Response") == "True":
                        imdb_id = res.get("imdbID")
                        id_source = "OMDb"
                        if "year" not in updates: updates["year"] = res.get("Year")
                        if "runtime" not in updates: updates["runtime"] = res.get("Runtime")
                        if "genre" not in updates: updates["genre"] = res.get("Genre")
                        if "plot" not in updates: updates["plot"] = res.get("Plot")
                        
                        # MUUTOS: Päivitetään kuva vain, jos elokuvalla EI OLE vielä kuvaa Kinoon.fi:stä
                        if not movie.get("poster_url") and "poster_url" not in updates and res.get("Poster") and res.get("Poster") != "N/A": 
                            updates["poster_url"] = res.get("Poster")
                        break 
                except Exception:
                    pass

        # VAIHE 3: Hae tarkka arvosana virallisesta datasetistä
        rating_source = "Ei ID:tä"
        if imdb_id:
            movie_data = ratings_db.get(imdb_id)
            if movie_data:
                updates["imdb_rating"] = movie_data["rating"]
                updates["imdb_votes"] = movie_data["votes"]
                rating_source = f"IMDb Dataset (ID via {id_source})"
            else:
                updates["imdb_rating"] = "N/A"
                updates["imdb_votes"] = "N/A"
                rating_source = f"Liian uusi/0 ääntä (ID via {id_source})"
        else:
            updates["imdb_rating"] = "N/A"
            updates["imdb_votes"] = "N/A"
            
        movie.update(updates)
        cache[cache_key] = updates
        print(f"  [{i}/{len(movie_list)}] {fin_title} -> Arvosana: {updates.get('imdb_rating')} ({rating_source})")

def main():
    print("🎬 Elokuvahaku käynnistyy...\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        all_movies = get_kinoon_movies(page) + get_kinot_movies(page)
        if not all_movies:
            browser.close()
            return
            
        unique_movies = merge_duplicates(all_movies)
        print(f"\n📊 Yhteensä {len(unique_movies)} uniikkia elokuvaa. Etsitään tiedot teatterisivuilta...")
        
        for i, movie in enumerate(unique_movies, 1):
            if movie.get("source") == "Kinoon.fi" and movie.get("url"):
                venues, orig_title, year = get_kinoon_details(page, movie["url"])
                if orig_title: movie["original_title"] = orig_title
                if year: movie["year"] = year
                    
                existing_theatres = {t["nimi"] for t in movie.get("esityspaikat", [])}
                for venue in venues:
                    if venue["nimi"] not in existing_theatres:
                        movie["esityspaikat"].append(venue)
                        existing_theatres.add(venue["nimi"])
                        
        browser.close()
        
    ratings_db = load_imdb_ratings()
    fetch_metadata_via_dataset(unique_movies, ratings_db)
    
    unique_movies.sort(
        key=lambda x: float(x.get("imdb_rating", 0)) if x.get("imdb_rating") and x.get("imdb_rating") != "N/A" else -1.0, 
        reverse=True
    )
    
    paivitetty_teksti = datetime.now().strftime("päivitetty %d.%m.%Y klo %H.%M")
    
    with open("leffat.json", "w", encoding="utf-8") as f:
        json.dump({"paivitetty": paivitetty_teksti, "elokuvat": unique_movies}, f, ensure_ascii=False, indent=2)
    
    print("\n✅ Valmis! Tiedosto tallennettu nimellä 'leffat.json'")

if __name__ == "__main__":
    main()

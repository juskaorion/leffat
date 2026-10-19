import os
import json
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import requests
from playwright.sync_api import sync_playwright

OMDB_API_KEY = os.getenv('OMDB_API_KEY', 'SINUN_OMDB_AVAIMESI_TÄHÄN')

# Tunnetuimpien pääkaupunkiseudun elokuvateattereiden suorat linkit
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
    """Palauttaa teatterin kotisivu- tai lippulinkin."""
    if direct_url and direct_url.startswith("http"):
        return direct_url
    for key, url in THEATRE_URL_MAP.items():
        if key.lower() in name.lower():
            return url
    return direct_url if direct_url else ""


def get_kinoon_movies(page):
    """Hakee Kinoon.fi:n elokuvat."""
    print("Haetaan Kinoon.fi elokuvia (selainmoottorilla)...")
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
                        "esityspaikat": []
                    })
                    
            except Exception:
                continue
                
    except Exception as e:
        print(f"Virhe Kinoon.fi datan haussa: {e}")
        
    print(f"Löydettiin {len(movies)} elokuvaa Kinoon.fi:stä")
    return movies


def get_kinot_movies(page):
    """Hakee Kinot.fi elokuvat ja esityspaikat ilman kellonaikoja."""
    print("Haetaan Kinot.fi elokuvia ja esityspaikkoja...")
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
                    theatre_name = texts[2].replace('>', '').strip()
                    
                    # Selvitetään teatterin linkki
                    theatre_url = resolve_theatre_url(theatre_name)
                    
                    search_title = title
                    if ": " in title:
                        search_title = title.split(": ")[-1]
                        
                    movies.append({
                        "title": title,
                        "search_title": search_title,
                        "url": url,
                        "source": "Kinot.fi",
                        "poster_url": None,
                        "esityspaikat": [{
                            "nimi": theatre_name,
                            "url": theatre_url,
                            "html": f'<a href="{theatre_url}" target="_blank" rel="noopener noreferrer">{theatre_name}</a>' if theatre_url else theatre_name
                        }]
                    })
            except Exception:
                continue
        
        print(f"Löydettiin {len(movies)} näytöstä Kinot.fi:stä")
                
    except Exception as e:
        print(f"Virhe Kinot.fi datan haussa: {e}")
        
    return movies


def get_kinoon_theatres(page, movie_url):
    """Hakee elokuvan esityspaikat Kinoon.fi-sivulta (ilman kellonaikoja)."""
    venues = []
    seen_venues = set()
    
    try:
        page.goto(movie_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)
        
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        showtime_divs = soup.find_all('div', class_=lambda x: x and 'flex items-center gap-3 px-3 py-3' in x)
        
        for div in showtime_divs:
            theatre_span = div.find('span', class_=lambda x: x and 'text-zinc-200' in x)
            if not theatre_span:
                continue
            theatre_name = theatre_span.get_text(strip=True)
            
            if theatre_name and theatre_name not in seen_venues:
                seen_venues.add(theatre_name)
                theatre_link = resolve_theatre_url(theatre_name)
                venues.append({
                    "nimi": theatre_name,
                    "url": theatre_link,
                    "html": f'<a href="{theatre_link}" target="_blank" rel="noopener noreferrer">{theatre_name}</a>' if theatre_link else theatre_name
                })
    
    except Exception as e:
        print(f"  Virhe teattereiden haussa: {e}")
    
    return venues


def merge_duplicates(movie_list):
    """Yhdistää saman elokuvan eri esiintymät ja yhdistää uniikit esityspaikat."""
    print("\nYhdistetään duplikaatit...")
    merged = {}
    
    for movie in movie_list:
        key = movie["search_title"].lower().strip()
        key = ' '.join(key.split())
        key = re.sub(r'\s*\(\d{4}\)\s*', '', key)
        
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
    
    result = list(merged.values())
    removed = len(movie_list) - len(result)
    print(f"Duplikaattien poiston jälkeen: {len(result)} uniikkia elokuvaa ({removed} duplikaattia poistettu)")
    return result


def fetch_omdb_data(movie_list):
    """Hakee tiedot OMDb API:sta."""
    print("\nHaetaan lisätietoja OMDb:stä...")
    
    if OMDB_API_KEY == "SINUN_OMDB_AVAIMESI_TÄHÄN":
        print("⚠️  OMDb API-avain puuttuu, ohitetaan lisätietojen haku.")
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
                
        except Exception:
            print(f"  [{i}/{len(movie_list)}] {search_title}: Virhe")


def main():
    print("🎬 Elokuvahaku käynnistyy...\n")
    print("Käynnistetään selainmoottori (Playwright)...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        kinoon_data = get_kinoon_movies(page)
        kinot_data = get_kinot_movies(page)
        
        all_movies = kinoon_data + kinot_data
        
        if not all_movies:
            print("\n❌ Yhtään elokuvaa ei löydetty.")
            browser.close()
            return
        
        unique_movies = merge_duplicates(all_movies)
        print(f"\n📊 Yhteensä {len(unique_movies)} uniikkia elokuvaa")
        
        fetch_omdb_data(unique_movies)
        
        # Järjestetään IMDb-arvosanan mukaan
        unique_movies.sort(
            key=lambda x: (
                float(x.get("imdb_rating", 0)) if x.get("imdb_rating") and x.get("imdb_rating") != "N/A" else -1.0
            ), 
            reverse=True
        )
        
        # Haetaan esityspaikat TOP 30 elokuvalle
        print(f"\n🏛️ Haetaan esityspaikat TOP 30 elokuvalle...\n")
        top_30 = [m for m in unique_movies if m.get("imdb_rating") and m.get("imdb_rating") != "N/A"][:30]
        
        for i, movie in enumerate(top_30, 1):
            if movie.get("source") == "Kinoon.fi" and movie.get("url"):
                print(f"  [{i}/30] {movie['title']}...")
                kinoon_venues = get_kinoon_theatres(page, movie["url"])
                
                existing_theatres = {t["nimi"] for t in movie.get("esityspaikat", [])}
                for venue in kinoon_venues:
                    if venue["nimi"] not in existing_theatres:
                        movie["esityspaikat"].append(venue)
                        existing_theatres.add(venue["nimi"])
        
        browser.close()
    
    # Luodaan aikaleima muodossa: "päivitetty xx.xx.xxxx klo xx.xx"
    paivitetty_teksti = datetime.now().strftime("päivitetty %d.%m.%Y klo %H.%M")
    
    # Tallennetaan JSON-tiedostoon sekä päivitysaika että elokuvat
    output_filename = "leffat.json"
    output_data = {
        "paivitetty": paivitetty_teksti,
        "elokuvat": unique_movies
    }
    
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    # Tulostetaan TOP 5 konsoliin
    print("\n🏆 TOP 5 ELOKUVAA (IMDb):")
    count = 0
    for movie in unique_movies:
        rating = movie.get('imdb_rating')
        if rating and rating != 'N/A':
            rt = movie.get('rt_rating', 'N/A')
            teatterit = [t["nimi"] for t in movie.get("esityspaikat", [])]
            teatterit_str = ", ".join(teatterit) if teatterit else "Ei listattuja teattereita"
            print(f"  {count+1}. {movie['title']}")
            print(f"     IMDb: {rating} | RT: {rt}")
            print(f"     Esityspaikat: {teatterit_str}")
            count += 1
            if count >= 5:
                break
    
    print(f"\n✅ Valmis! Tiedot tallennettu: {output_filename}")
    print(f"🕒 Aikaleima: {paivitetty_teksti}")
    print(f"📍 Esityspaikat haettu linkkeinä ilman kellonaikoja.")

if __name__ == "__main__":
    main()

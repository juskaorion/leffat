import os
import sys
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
    if direct_url and direct_url.startswith("http"):
        return direct_url
    for key, url in THEATRE_URL_MAP.items():
        if key.lower() in name.lower():
            return url
    return direct_url if direct_url else ""

def is_invalid_title(title):
    if not title:
        return True
    t = title.strip().lower()
    return "juliste uupuu" in t or t in {"ei julistetta", "n/a"}

def clean_title_for_search(title):
    if not title:
        return ""
    
    # 1. Poistetaan sulkeissa ja hakasulkeissa olevat lisätiedot, esim. (ennakkokuuntelu)
    cleaned = re.sub(r'[\(\[].*?[\)\]]', '', title)

    # 2. Poistetaan tunnetut festivaali-, sarja- ja erikoisnäytösetuliitteet alusta (myös ketjutettuna)
    prefix_pattern = re.compile(
        r'^(?:'
        r'NV\d*\s*[:\-–]\s*|'
        r'Night\s+Visions(?:\s+\d+)?\s*[:\-–]\s*|'
        r'R&A\s*[:\-–]\s*|'
        r'KAVI(?:\s+esittää)?\s*[:\-–]\s*|'
        r'Kino\s*[:\-–]\s*|'
        r'Päätöselokuva\s*[:\-–]\s*|'
        r'Avajaiselokuva\s*[:\-–]\s*|'
        r'Yllätyselokuva\s*[:\-–]\s*|'
        r'Erikoisnäytös\s*[:\-–]\s*|'
        r'Ennakkonäytös\s*[:\-–]\s*|'
        r'Tekijätorstai\s*[:\-–]\s*|'
        r'Klassikko(?:näytös)?\s*[:\-–]\s*|'
        r'Kuukauden\s+elokuva\s*[:\-–]\s*|'
        r'Senioribio\s*[:\-–]\s*|'
        r'Vauvakino\s*[:\-–]\s*'
        r')+',
        flags=re.IGNORECASE
    )
    cleaned = prefix_pattern.sub('', cleaned)

    # 3. Poistetaan lopusta oheistapahtumat, esim. "& Renny Harlin Masterclass"
    cleaned = re.sub(
        r'\s+(?:&|\+)\s+.*?(?:masterclass|keskustelu|tekijävierailu|q&a|live).*$',
        '',
        cleaned,
        flags=re.IGNORECASE
    )

    # 4. Poistetaan formaatti- ja tekniikkamerkinnät (2D, 3D, 4K, IMAX, dub, jne.)
    cleaned = re.sub(
        r'\b(2D|3D|4K|IMAX|dub|dubattu|orig|kavi|sing-along|preview|ennakko|restauroitu|restoration)\b',
        '',
        cleaned,
        flags=re.IGNORECASE
    )

    # 5. Siistitään ylimääräiset välilyönnit ja reunaviivat
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -–—:/')
    return cleaned

def build_search_titles(raw_title, original_title=None):
    """Generoi hakuvaihtoehdot tärkeysjärjestyksessä."""
    candidates = []

    def add_candidate(t):
        if not t:
            return
        c = t.strip(' -–—:/')
        if len(c) >= 2 and c.lower() not in [x.lower() for x in candidates]:
            candidates.append(c)

    orig_clean = clean_title_for_search(original_title) if original_title else ""
    fin_clean = clean_title_for_search(raw_title)

    if orig_clean:
        add_candidate(orig_clean)
    if fin_clean:
        add_candidate(fin_clean)

    # Jos nimessä on teemasarjan numero + kaksoispiste (esim. "Verenimijät 2: Fascination")
    series_match = re.match(r'^.+?\s+\d+\s*:\s*(.+)$', fin_clean)
    if series_match:
        add_candidate(series_match.group(1))

    # Jos nimessä on väliviivalla erotettu kaksoisnimi (esim. "Gaua - The Night" tai "Wicker - Intohimosta punottu")
    for base in [orig_clean, fin_clean]:
        if not base:
            continue
        if re.search(r'\s+[-–—]\s+', base):
            parts = [p.strip() for p in re.split(r'\s+[-–—]\s+', base) if p.strip()]
            for p in parts:
                if len(p) >= 3:
                    add_candidate(p)
        if ':' in base:
            parts = [p.strip() for p in base.split(':') if p.strip()]
            # Kokeillaan sekä loppuosaa (esim. teemasarjan jälkeen) että alkuosaa (esim. pääotsikko ennen alaotsikkoa)
            if len(parts) >= 2:
                add_candidate(parts[-1])
                add_candidate(parts[0])

    return candidates

def get_kinoon_movies(page):
    print("Haetaan Kinoon.fi elokuvia...")
    movies, seen_titles = [], set()
    try:
        page.goto("https://kinoon.fi/helsinki/elokuvat-ja-esitysajat", wait_until="networkidle", timeout=45000)
        
        # Hyväksytään evästeet kerran heti alussa
        try:
            btn = page.locator('button', has_text=re.compile(r"Hyväksy|Salli|Kyllä|Accept", re.IGNORECASE)).first
            if btn.is_visible(timeout=3000):
                btn.click()
                page.wait_for_timeout(500)
        except Exception:
            pass

        page.wait_for_selector('[data-film-card-id]', timeout=20000)
        
        prev_height = 0
        for _ in range(10):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            curr_height = page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                break
            prev_height = curr_height

        soup = BeautifulSoup(page.content(), 'html.parser')
        
        for card in soup.find_all('div', attrs={'data-film-card-id': True}):
            try:
                link = card.find('a')
                if not link:
                    continue
                
                title = ""
                img = card.find('img')
                
                # 1. Kuvan alt-teksti (kunhan ei ole "Juliste uupuu")
                if img and img.get('alt') and not is_invalid_title(img.get('alt')):
                    title = img['alt'].strip()
                
                # 2. Varsinaiset otsikkotagit (h1-h4) ennen p/span-elementtejä
                if not title:
                    heading = card.find(['h1', 'h2', 'h3', 'h4'])
                    if heading and not is_invalid_title(heading.get_text(strip=True)):
                        title = heading.get_text(strip=True)
                
                # 3. Varalla p/span, mutta ohitetaan "Juliste uupuu :(" ja ikärajat
                if not title:
                    for elem in card.find_all(['p', 'span']):
                        txt = elem.get_text(strip=True)
                        if txt and not is_invalid_title(txt) and len(txt) > 2:
                            title = txt
                            break
                
                if is_invalid_title(title) or title in seen_titles:
                    continue
                
                seen_titles.add(title)
                url = "https://kinoon.fi" + link.get('href', '')
                
                poster_url = img.get('src', '') if img else ''
                if poster_url and not poster_url.startswith('http'):
                    poster_url = "https://kinoon.fi" + poster_url
                
                movies.append({
                    "title": title,
                    "search_title": title,
                    "url": url,
                    "source": "Kinoon.fi",
                    "poster_url": poster_url or None,
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
        
        for item in soup.find_all('div', class_='show-item'):
            try:
                link_elem = item.find('a')
                url = "https://www.kinot.fi" + link_elem['href'] if link_elem and link_elem.has_attr('href') else ""
                text_wrapper = item.find('div', class_='text-wrapper')
                if not text_wrapper:
                    continue
                texts = list(text_wrapper.stripped_strings)
                if len(texts) >= 3:
                    title, theatre_name = texts[0], texts[2].replace('>', '').strip()
                    if is_invalid_title(title):
                        continue
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
    venues, original_title, year, seen_venues = [], None, None, set()
    try:
        page.goto(movie_url, wait_until="domcontentloaded", timeout=15000)
        try:
            page.wait_for_selector('h1, .fdp-reveal-title', timeout=4000)
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
                    venues.append({
                        "nimi": t_name,
                        "url": t_link,
                        "html": f'<a href="{t_link}" target="_blank">{t_name}</a>' if t_link else t_name
                    })
        
        title_container = soup.find('div', class_=lambda x: x and 'fdp-reveal-title' in x)
        if title_container:
            for sub in title_container.find_all(['span', 'p'], class_=lambda x: x and ('text-zinc-200' in x or 'text-zinc-300' in x)):
                sub_text = sub.get_text(strip=True)
                # Varmistetaan ettei alkuperäisnimeksi napata pelkkää vuosilukua tai kestoa
                if sub_text and not re.match(r'^\d{4}$', sub_text) and not re.search(r'\b\d+\s*min\b', sub_text.lower()):
                    original_title = sub_text
                    break
            
            # Poistetaan pääotsikko ennen vuosiluvun etsimistä (jotta esim. "TC 2000" ei tulkitse vuotta 2000 julkaisuvuodeksi)
            h1_text = title_container.find('h1').get_text() if title_container.find('h1') else ""
            meta_text = title_container.get_text().replace(h1_text, "")
            year_match = re.search(r'\b(19\d{2}|20\d{2})\b', meta_text)
            if year_match:
                year = year_match.group(0)
    except Exception:
        pass
    return venues, original_title, year

def merge_duplicates(movie_list):
    merged = {}
    for movie in movie_list:
        if is_invalid_title(movie.get("title")):
            continue
        key = clean_title_for_search(movie["search_title"]).lower()
        if not key or is_invalid_title(key):
            continue
            
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

def load_imdb_ratings():
    print("\n📥 Ladataan IMDb:n virallista arvosanatietokantaa (n. 7 MB)...")
    url = "https://datasets.imdbws.com/title.ratings.tsv.gz"
    res = requests.get(url, timeout=30)
    content = gzip.decompress(res.content).decode('utf-8')
    ratings = {}
    reader = csv.reader(content.splitlines(), delimiter='\t')
    next(reader)
    for row in reader:
        if len(row) == 3:
            ratings[row[0]] = {"rating": row[1], "votes": row[2]}
    print(f"✅ Ladattu arvosanat {len(ratings):,} elokuvalle/sarjalle!")
    return ratings

def search_tmdb_best_match(search_title, expected_year, ratings_db):
    """Hakee TMDB:stä ja suosii osumaa, jolta löytyy IMDb-tunniste ja arvosana."""
    if not TMDB_API_KEY:
        return None
    try:
        search_params = {"api_key": TMDB_API_KEY, "query": search_title, "language": "fi-FI"}
        if expected_year:
            search_params["primary_release_year"] = expected_year
        
        res = requests.get("https://api.themoviedb.org/3/search/movie", params=search_params, timeout=5).json()
        results = res.get("results") or []

        # Jos vuodella rajattu haku ei tuota tulosta, haetaan ilman vuodelle pakotettua rajausta
        if not results and expected_year:
            search_params.pop("primary_release_year", None)
            res = requests.get("https://api.themoviedb.org/3/search/movie", params=search_params, timeout=5).json()
            results = res.get("results") or []

        if not results:
            return None

        fallback_candidate = None
        # Tarkistetaan enintään 4 kärkiosumaa, jotta ei jäädä jumiin arvioimattomaan lyhytelokuvaan
        for candidate in results[:4]:
            detail_url = f"https://api.themoviedb.org/3/movie/{candidate['id']}?api_key={TMDB_API_KEY}&language=fi-FI"
            detail_res = requests.get(detail_url, timeout=5).json()
            imdb_id = detail_res.get("imdb_id")

            if fallback_candidate is None:
                fallback_candidate = (candidate, detail_res, imdb_id)

            # Jos tällä osumalla on jo arvosana IMDb-datasetissä, valitaan se heti
            if imdb_id and imdb_id in ratings_db:
                return (candidate, detail_res, imdb_id)

        # Jos millään kärkiosumalla ei ollut arvosanaa mutta jollain oli imdb_id, palautetaan ensimmäinen
        return fallback_candidate
    except Exception:
        return None

def fetch_metadata_via_dataset(movie_list, ratings_db):
    print("\nHaetaan elokuvien lisätiedot API-rajapinnoista (TMDB ensin, sitten OMDb) ja arvosanat datasetistä...")
    cache = {}

    for i, movie in enumerate(movie_list, 1):
        raw_title = movie["search_title"]
        orig_title = movie.get("original_title", "")
        expected_year = movie.get("year")
        
        titles_to_try = build_search_titles(raw_title, orig_title)
        primary_clean = titles_to_try[0] if titles_to_try else raw_title

        cache_key = f"{primary_clean.lower()}_{expected_year}"
        if cache_key in cache:
            movie.update(cache[cache_key])
            print(f"  [{i}/{len(movie_list)}] Osuma välimuistista: '{primary_clean}' -> Arvosana: {movie.get('imdb_rating')}")
            continue

        updates = {}
        imdb_id = None
        omdb_fallback_rating = None
        id_source = ""

        # VAIHE 1: TMDB
        for search_title in titles_to_try:
            match = search_tmdb_best_match(search_title, expected_year, ratings_db)
            if match:
                best_match, detail_res, found_imdb_id = match
                updates["year"] = best_match.get("release_date", "")[:4] if best_match.get("release_date") else expected_year
                updates["plot"] = detail_res.get("overview") or best_match.get("overview")
                updates["genre"] = ", ".join([g["name"] for g in detail_res.get("genres", [])])
                updates["runtime"] = f"{detail_res.get('runtime')} min" if detail_res.get("runtime") else None
                
                if not movie.get("poster_url") and best_match.get("poster_path"):
                    updates["poster_url"] = f"https://image.tmdb.org/t/p/w500{best_match.get('poster_path')}"

                if found_imdb_id:
                    imdb_id = found_imdb_id
                    id_source = f"TMDB ('{search_title}')"
                    # Jos löytyi jo arvosanallinen osuma, lopetetaan hakeminen
                    if imdb_id in ratings_db:
                        break

        # VAIHE 2: OMDb - Jos TMDB ei löytänyt IMDb ID:tä tai arvosanaa
        if (not imdb_id or imdb_id not in ratings_db) and OMDB_API_KEY:
            for search_title in titles_to_try:
                # Kokeillaan ensin vuosiluvulla ja tarvittaessa ilman vuosilukua
                years_to_try = [expected_year, None] if expected_year else [None]
                found_in_omdb = False
                for y in years_to_try:
                    try:
                        params = {"apikey": OMDB_API_KEY, "t": search_title, "plot": "short"}
                        if y:
                            params["y"] = y
                        res = requests.get(f"http://www.omdbapi.com/?{urllib.parse.urlencode(params)}", timeout=5).json()
                        
                        if res.get("Response") == "True" and res.get("imdbID"):
                            imdb_id = res.get("imdbID")
                            id_source = f"OMDb ('{search_title}')"
                            if res.get("imdbRating") and res.get("imdbRating") != "N/A":
                                omdb_fallback_rating = res.get("imdbRating")
                            if not updates.get("year") and res.get("Year") != "N/A":
                                updates["year"] = res.get("Year")
                            if not updates.get("runtime") and res.get("Runtime") != "N/A":
                                updates["runtime"] = res.get("Runtime")
                            if not updates.get("genre") and res.get("Genre") != "N/A":
                                updates["genre"] = res.get("Genre")
                            if not updates.get("plot") and res.get("Plot") != "N/A":
                                updates["plot"] = res.get("Plot")
                            if not movie.get("poster_url") and "poster_url" not in updates and res.get("Poster") not in (None, "N/A"):
                                updates["poster_url"] = res.get("Poster")
                            found_in_omdb = True
                            break
                    except Exception:
                        pass
                if found_in_omdb:
                    break

        # VAIHE 3: Hae tarkka arvosana virallisesta datasetistä (tai OMDb-varahausta)
        rating_source = "Ei ID:tä"
        if imdb_id:
            updates["imdb_id"] = imdb_id
            movie_data = ratings_db.get(imdb_id)
            if movie_data:
                updates["imdb_rating"] = movie_data["rating"]
                updates["imdb_votes"] = movie_data["votes"]
                rating_source = f"IMDb Dataset ({id_source})"
            elif omdb_fallback_rating:
                updates["imdb_rating"] = omdb_fallback_rating
                updates["imdb_votes"] = "N/A"
                rating_source = f"OMDb API ({id_source})"
            else:
                updates["imdb_rating"] = "N/A"
                updates["imdb_votes"] = "N/A"
                rating_source = f"Liian uusi/0 ääntä ({id_source})"
        else:
            updates["imdb_rating"] = "N/A"
            updates["imdb_votes"] = "N/A"
            
        movie.update(updates)
        cache[cache_key] = updates
        print(f"  [{i}/{len(movie_list)}] {raw_title} -> Haku: {titles_to_try} -> ⭐ {updates.get('imdb_rating')} ({rating_source})")

def run_terminal_test():
    """Testaa kuvakaappausten ongelmanimet nopeasti terminaalissa ilman selainta."""
    test_titles = [
        "NV26: Hard Boiled 4k",
        "NV26: Swamp Thing",
        "NV26: Faces of Death",
        "NV26: Dernsie: The Amazing Life of Bruce Dern",
        "NV26: Phí Phông: The Blood Demon",
        "NV26: Gaua - The Night",
        "NV26: The Beast & Renny Harlin Masterclass",
        "NV26: Mineshaft: The Cruising Murders",
        "NV26: Body Blow",
        "NV26: Rosebush Pruning",
        "NV26: Onslaught",
        "NV26: Buffet Infinity",
        "Tekijätorstai: Tove",
        "Verenimijät 2: Fascination",
        "Wicker - Intohimosta punottu",
        "Ebenezer: Saiturin joulu",
        "Juliste uupuu :("
    ]
    print("🧪 Ajetaan terminaalitesti ongelmanimille...\n")
    test_movies = [{"title": t, "search_title": t, "esityspaikat": [], "poster_url": None} for t in test_titles]
    test_movies = merge_duplicates(test_movies)
    
    ratings_db = load_imdb_ratings()
    fetch_metadata_via_dataset(test_movies, ratings_db)

def main():
    if "--test" in sys.argv:
        run_terminal_test()
        return

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
                if orig_title:
                    movie["original_title"] = orig_title
                if year:
                    movie["year"] = year
                    
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

const JSON_URL = 'https://raw.githubusercontent.com/juskaorion/leffat/main/leffat.json';

let allMovies = [];
let lastUpdated = '';

async function loadMovies() {
  try {
    const response = await fetch(JSON_URL + '?t=' + Date.now());
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: Tarkista että repo on julkinen ja URL oikein`);
    }
    
    const data = await response.json();

    // Lukee uuden rakenteen { paivitetty, elokuvat }
    if (Array.isArray(data)) {
      allMovies = data;
      lastUpdated = '';
    } else {
      allMovies = data.elokuvat || [];
      lastUpdated = data.paivitetty || '';
    }

    renderMovies(allMovies);
    
  } catch (error) {
    console.error('Virhe:', error);
    document.getElementById('elokuvat-app').innerHTML = `
      <div class="error">
        <h2>⚠️ Virhe ladattaessa elokuvia</h2>
        <p>${error.message}</p>
        <p><strong>Tarkista URL:</strong> ${JSON_URL}</p>
      </div>
    `;
  }
}

function renderMovies(movies) {
  const app = document.getElementById('elokuvat-app');
  
  const withRatings = movies.filter(m => m.imdb_rating && m.imdb_rating !== 'N/A').length;
  const totalVenues = movies.reduce((sum, m) => sum + (m.esityspaikat?.length || 0), 0);
  
  let html = `
    <div class="header">
      <h1>🎬 Elokuvat tällä viikolla</h1>
      <div class="update-time">${lastUpdated || 'Päivitetty tällä viikolla'}</div>
      <div class="stats">
        <div class="stat">
          <div class="stat-number">${movies.length}</div>
          <div class="stat-label">Elokuvaa</div>
        </div>
        <div class="stat">
          <div class="stat-number">${withRatings}</div>
          <div class="stat-label">Arvioitua</div>
        </div>
        <div class="stat">
          <div class="stat-number">${totalVenues}</div>
          <div class="stat-label">Esityspaikkaa</div>
        </div>
      </div>
    </div>
    
    <div class="filters">
      <button class="filter-btn active" onclick="filterMovies('all', event)">Kaikki (${movies.length})</button>
      <button class="filter-btn" onclick="filterMovies('high-rated', event)">⭐ Yli 7.5</button>
      <button class="filter-btn" onclick="filterMovies('new', event)">🆕 Uudet</button>
    </div>
    
    <div class="movies-grid">
  `;
  
  movies.forEach(movie => {
    const imdb = movie.imdb_rating || 'N/A';
    const rt = movie.rt_rating || null;
    const genre = movie.genre || 'N/A';
    const year = movie.year || 'N/A';
    const runtime = movie.runtime || 'N/A';
    const plot = movie.plot || '';
    const poster = movie.poster_url || 'https://via.placeholder.com/300x450/667eea/ffffff?text=Ei+julistetta';
    
    const genres = genre !== 'N/A' ? genre.split(',').slice(0, 3) : [];
    const genreTags = genres.map(g => `<span class="genre-tag">${g.trim()}</span>`).join('');
    
    // Esityspaikat linkkeinä
    let venuesHtml = '';
    const venues = movie.esityspaikat || [];

    if (venues.length > 0) {
      const links = venues.map(venue => {
        if (venue.url) {
          return `<a href="${venue.url}" class="venue-link" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">${venue.nimi}</a>`;
        }
        return `<span class="venue-name">${venue.nimi}</span>`;
      }).join('');

      venuesHtml = `
        <div class="venues-container" style="margin-top:10px;">
          <div class="venues-title" style="font-weight:bold; font-size:0.85rem; margin-bottom:4px;">📍 Esityspaikat:</div>
          <div class="venues-list" style="display:flex; flex-wrap:wrap; gap:6px;">${links}</div>
        </div>
      `;
    } else {
      venuesHtml = '<div class="no-venues" style="font-size:0.8rem; opacity:0.7; margin-top:6px;">Ei listattuja teattereita tällä viikolla</div>';
    }
    
    html += `
      <div class="movie-card" 
           data-rating="${imdb}" 
           data-year="${year}" 
           data-genre="${genre.toLowerCase()}"
           onclick="window.open('${movie.url}', '_blank')">
        <img src="${poster}" alt="${movie.title}" class="movie-poster" loading="lazy">
        <div class="movie-info">
          <h2 class="movie-title">${movie.title}</h2>
          
          <div class="ratings">
            <div class="rating imdb">⭐ ${imdb}</div>
            ${rt ? `<div class="rating rt">🍅 ${rt}</div>` : ''}
          </div>
          
          <div class="genre-tags">${genreTags}</div>
          
          <div class="movie-meta">${year} • ${runtime}</div>
          
          ${plot ? `<div class="plot">${plot}</div>` : ''}
          
          ${venuesHtml}
        </div>
      </div>
    `;
  });
  
  html += '</div>';
  app.innerHTML = html;
}

function filterMovies(filter, event) {
  document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
  event.target.classList.add('active');
  
  let filtered = allMovies;
  
  if (filter === 'high-rated') {
    filtered = allMovies.filter(m => {
      const rating = parseFloat(m.imdb_rating);
      return rating >= 7.5;
    });
  } else if (filter === 'new') {
    const currentYear = new Date().getFullYear();
    filtered = allMovies.filter(m => {
      const year = parseInt(m.year);
      return year >= currentYear - 1;
    });
  } else if (filter !== 'all') {
    filtered = allMovies.filter(m => {
      const genre = (m.genre || '').toLowerCase();
      return genre.includes(filter);
    });
  }
  
  renderMovies(filtered);
}

loadMovies();

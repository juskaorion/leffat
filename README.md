# 🎬 Elokuvat Scraper

Automaattinen elokuvien hakija Kinoon.fi:stä ja Kinot.fi:stä.

## 🚀 Toiminta

- Ajetaan automaattisesti GitHub Actionsilla **tiistaisin ja perjantaisin klo 08:00**
- Hakee elokuvat + esitysajat
- Rikastaa dataa OMDb:stä (IMDb, Rotten Tomatoes, julisteet)
- Tallentaa JSON:n jota WordPress-sivu lukee

## 📊 Data

`leffat.json` sisältää:
- Elokuvan nimi, vuosi, genre
- IMDb & Rotten Tomatoes -arvosanat
- Julistekuva
- Esitysajat teattereittain

## 🔧 Käyttö

WordPress-sivu lukee JSON:n:
```javascript
fetch('https://raw.githubusercontent.com/juskaorion/leffat/main/leffat.json')

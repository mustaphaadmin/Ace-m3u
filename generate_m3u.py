#!/usr/bin/env python3
"""
Script que consulta la API de Ace Stream y genera un archivo .m3u
con enlaces directos al reproductor local.
Se ejecuta automáticamente vía GitHub Actions.
"""

import requests
import json
import re
import os
import sys
from datetime import datetime, timezone

# ============ CONFIGURACIÓN ============
# URL de la API de Ace Stream (cambia si tienes otra)
API_URL = "https://api.acestream.me/all?api_version=1.0&api_key=test_api_key"

# URL base de tu reproductor Ace Stream local
# GitHub Actions NO puede acceder a tu red local, así que ponemos la IP directamente
ACE_STREAM_BASE = "http://192.168.1.141:6878/ace/getstream?id="

# País por defecto si no se detecta
DEFAULT_COUNTRY = "Desconocido"

# Número máximo de canales a incluir
MAX_CHANNELS = 500

# Archivo de salida
OUTPUT_FILE = "acestream_channels.m3u"


# ============ DETECCIÓN DE PAÍS ============
def detect_country(name):
    """Intenta detectar el país a partir del nombre del canal."""
    if not name:
        return DEFAULT_COUNTRY
    
    upper = name.upper().strip()
    
    patterns = [
        (r'ESPA[ÑN]A|SPAIN', 'España'),
        (r'M[ÉE]XICO|MEXICO', 'México'),
        (r'ARGENTINA', 'Argentina'),
        (r'COLOMBIA', 'Colombia'),
        (r'CHILE', 'Chile'),
        (r'PER[ÚU]|PERU', 'Perú'),
        (r'ESTADOS\s*UNIDOS|USA|UNITED\s*STATES|^US\b', 'USA'),
        (r'REINO\s*UNIDO|UNITED\s*KINGDOM|UK|ENGLAND|INGLATERRA', 'UK'),
        (r'FRANCIA|FRANCE', 'Francia'),
        (r'ALEMANIA|GERMANY|DEUTSCH', 'Alemania'),
        (r'ITALIA|ITALY', 'Italia'),
        (r'PORTUGAL', 'Portugal'),
        (r'BRASIL|BRAZIL', 'Brasil'),
        (r'RUSIA|RUSSIA', 'Rusia'),
        (r'INDIA', 'India'),
        (r'JAP[ÓO]N|JAPAN', 'Japón'),
        (r'COREA|KOREA', 'Corea del Sur'),
        (r'CHINA', 'China'),
        (r'CANAD[ÁA]|CANADA', 'Canadá'),
        (r'AUSTRALIA', 'Australia'),
        (r'URUGUAY', 'Uruguay'),
        (r'ECUADOR', 'Ecuador'),
        (r'VENEZUELA', 'Venezuela'),
        (r'BOLIVIA', 'Bolivia'),
        (r'PARAGUAY', 'Paraguay'),
        (r'COSTA\s*RICA', 'Costa Rica'),
        (r'PANAM[ÁA]|PANAMA', 'Panamá'),
        (r'REP[ÚU]BLICA\s*DOMINICANA|DOMINICANA', 'Rep. Dominicana'),
        (r'CUBA', 'Cuba'),
        (r'GUATEMALA', 'Guatemala'),
        (r'HONDURAS', 'Honduras'),
        (r'EL\s*SALVADOR', 'El Salvador'),
        (r'NICARAGUA', 'Nicaragua'),
        (r'PUERTO\s*RICO', 'Puerto Rico'),
        (r'LATINO|LATAM', 'Latinoamérica'),
        (r'EUROPA|EUROPE|^EU\b', 'Europa'),
        (r'INTERNACIONAL|INTERNATIONAL', 'Internacional'),
    ]
    
    for pattern, country in patterns:
        if re.search(pattern, upper):
            return country
    
    # Buscar entre paréntesis
    paren_match = re.search(r'\(([^)]+)\)', name)
    if paren_match:
        return detect_country(paren_match.group(1))
    
    return DEFAULT_COUNTRY


# ============ EXTRAER CANALES ============
def extract_channels(data):
    """Extrae los canales de la respuesta JSON, soportando múltiples formatos."""
    channels = []
    
    if isinstance(data, list):
        channels = data
    elif isinstance(data, dict):
        # Buscar en claves comunes
        for key in ['channels', 'result', 'data', 'items', 'streams', 'list', 'response', 'content', 'results']:
            if isinstance(data.get(key), list) and len(data[key]) > 0:
                channels = data[key]
                break
        
        # Si no encontró, buscar cualquier array
        if not channels:
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 0:
                    channels = value
                    break
        
        # Buscar anidado
        if not channels:
            for key, value in data.items():
                if isinstance(value, dict):
                    nested = extract_channels(value)
                    if nested:
                        channels = nested
                        break
    
    return channels


def normalize_channel(ch):
    """Normaliza un canal a formato estándar."""
    name = ''
    hash_val = ''
    country = ''
    
    if isinstance(ch, str):
        parts = ch.split('|')
        if len(parts) >= 2:
            name = parts[0].strip()
            hash_val = parts[1].strip()
        else:
            hash_val = ch.strip()
            name = f"Stream {hash_val[:10]}..."
    
    elif isinstance(ch, dict):
        name = ch.get('name') or ch.get('title') or ch.get('channel_name') or ch.get('label') or ch.get('description') or ''
        hash_val = ch.get('hash') or ch.get('infohash') or ch.get('id') or ch.get('content_id') or ch.get('stream_id') or ch.get('magnet') or ''
        country = ch.get('country') or ch.get('region') or ch.get('category') or ch.get('group') or ch.get('language') or ''
        
        # Extraer hash de URL si existe
        if not hash_val and ch.get('url'):
            match = re.search(r'[a-fA-F0-9]{40}', ch['url'])
            if match:
                hash_val = match.group(0)
    
    # Si el nombre es un hash, intercambiar
    if not hash_val and name and re.match(r'^[a-fA-F0-9]{40}$', name):
        hash_val = name
        name = f"Stream {hash_val[:10]}..."
    
    if not name and hash_val:
        name = f"Canal {hash_val[:12]}..."
    
    if not country:
        country = detect_country(name)
    
    return {
        'name': name.strip() or 'Sin nombre',
        'hash': hash_val.strip() if hash_val else '',
        'country': country.strip() or DEFAULT_COUNTRY
    }


# ============ GENERAR M3U ============
def generate_m3u(channels, output_file):
    """Genera el archivo .m3u con los canales agrupados por país."""
    
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    total = len(channels)
    
    # Agrupar por país
    grouped = {}
    for ch in channels:
        country = ch['country']
        if country not in grouped:
            grouped[country] = []
        grouped[country].append(ch)
    
    # Ordenar países
    priority = ['España', 'México', 'Argentina', 'Colombia', 'Chile', 'Perú', 'USA', 'UK',
                'Francia', 'Alemania', 'Italia', 'Portugal', 'Brasil', 'Latinoamérica', 
                'Europa', 'Internacional']
    
    sorted_countries = sorted(grouped.keys(), key=lambda c: (
        priority.index(c) if c in priority else 999,
        c
    ))
    
    # Construir M3U
    m3u_lines = ['#EXTM3U']
    m3u_lines.append(f'#PLAYLIST: Ace Stream Channels')
    m3u_lines.append(f'# Actualizado: {now}')
    m3u_lines.append(f'# Total canales: {total}')
    m3u_lines.append(f'# Repositorio: https://github.com/tu-usuario/tu-repo')
    m3u_lines.append('')
    
    for country in sorted_countries:
        country_channels = grouped[country]
        m3u_lines.append(f'# ===== {country} ({len(country_channels)} canales) =====')
        m3u_lines.append('')
        
        # Ordenar canales alfabéticamente
        country_channels.sort(key=lambda c: c['name'].lower())
        
        for ch in country_channels:
            url = f"{ACE_STREAM_BASE}{ch['hash']}" if ch['hash'] else ''
            # EXTINF: duración(-1=live), atributos, nombre
            m3u_lines.append(f'#EXTINF:-1 group-title="{ch["country"]}" tvg-id="{ch["hash"][:20]}" tvg-logo="" ,{ch["name"]}')
            m3u_lines.append(url)
            m3u_lines.append('')
    
    # Escribir archivo
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(m3u_lines))
        f.write('\n')
    
    return total


# ============ MAIN ============
def main():
    print(f"🔄 Consultando API: {API_URL}")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; AceStreamM3UGenerator/1.0)',
            'Accept': 'application/json'
        }
        response = requests.get(API_URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Intentar parsear JSON
        try:
            data = response.json()
        except json.JSONDecodeError:
            print(f"❌ Error: La respuesta no es JSON válido")
            print(f"   Primeros 500 caracteres: {response.text[:500]}")
            sys.exit(1)
        
        # Extraer canales
        raw_channels = extract_channels(data)
        print(f"📊 Canales extraídos (raw): {len(raw_channels)}")
        
        if not raw_channels:
            print("⚠️  No se encontraron canales en la respuesta.")
            print(f"   Claves disponibles: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
            sys.exit(1)
        
        # Normalizar
        channels = []
        for ch in raw_channels:
            normalized = normalize_channel(ch)
            if normalized['hash'] and len(normalized['hash']) >= 30:
                channels.append(normalized)
        
        print(f"✅ Canales válidos (con hash): {len(channels)}")
        
        # Limitar
        if len(channels) > MAX_CHANNELS:
            channels = channels[:MAX_CHANNELS]
            print(f"⚠️  Limitado a {MAX_CHANNELS} canales")
        
        # Generar M3U
        total = generate_m3u(channels, OUTPUT_FILE)
        
        # Mostrar resumen por país
        countries = {}
        for ch in channels:
            countries[ch['country']] = countries.get(ch['country'], 0) + 1
        
        print(f"\n📺 Archivo generado: {OUTPUT_FILE}")
        print(f"📈 Total canales: {total}")
        print(f"\n🌍 Distribución por país:")
        for country, count in sorted(countries.items(), key=lambda x: -x[1]):
            print(f"   {country}: {count}")
        
        # Guardar metadata
        metadata = {
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'total_channels': total,
            'api_url': API_URL,
            'countries': countries
        }
        with open('metadata.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"\n📝 Metadata guardada en metadata.json")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error de conexión: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

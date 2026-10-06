import re
import html
import hashlib
import datetime as dt
import xml.etree.ElementTree as ET

from email.utils import format_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE_URL = "https://www.20minutos.es"

SECTION_URL = (
    "https://www.20minutos.es/lainformacion/empresas/"
)

OUTPUT_FILE = "feed.xml"

# Número máximo de páginas de la sección que intentaremos revisar.
MAX_PAGES = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


# ============================================================
# LIMPIEZA
# ============================================================

def clean_text(value):

    if not value:
        return ""

    value = html.unescape(str(value))

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def clean_url(url):

    if not url:
        return ""

    parts = urlsplit(url)

    # Eliminamos query y fragmentos para evitar duplicados.
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            "",
            "",
        )
    )


# ============================================================
# COMPROBAR URL DE ARTÍCULO
# ============================================================

def valid_article_url(url):

    if not url:
        return False

    url = clean_url(url)

    if not url.startswith(
        "https://www.20minutos.es/"
    ):
        return False

    if "/lainformacion/empresas/" not in url:
        return False

    normalized = url.rstrip("/")

    # Excluir la portada de Empresas.
    if normalized == SECTION_URL.rstrip("/"):
        return False

    # Excluir posibles páginas de paginación.
    if re.search(
        r"/lainformacion/empresas/(?:pagina-)?\d+$",
        normalized,
        flags=re.I,
    ):
        return False

    return True


# ============================================================
# DESCARGA
# ============================================================

def download(url):

    print(
        f"Descargando: {url}"
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=45,
    )

    response.raise_for_status()

    return response.text


# ============================================================
# FECHAS
# ============================================================

def parse_date_string(value):

    if not value:
        return None

    value = clean_text(value)

    # --------------------------------------------
    # ISO 8601
    # --------------------------------------------

    try:

        iso = value.replace(
            "Z",
            "+00:00"
        )

        parsed = dt.datetime.fromisoformat(
            iso
        )

        if parsed.tzinfo is None:

            parsed = parsed.replace(
                tzinfo=dt.timezone.utc
            )

        return parsed

    except Exception:
        pass

    # --------------------------------------------
    # dd/mm/yyyy
    # --------------------------------------------

    match = re.search(
        r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})"
        r"(?:\s+(\d{1,2}):(\d{2}))?",
        value,
    )

    if match:

        try:

            day = int(
                match.group(1)
            )

            month = int(
                match.group(2)
            )

            year = int(
                match.group(3)
            )

            hour = int(
                match.group(4) or 0
            )

            minute = int(
                match.group(5) or 0
            )

            return dt.datetime(
                year,
                month,
                day,
                hour,
                minute,
                tzinfo=dt.timezone.utc,
            )

        except Exception:
            pass

    return None


def extract_date(soup):

    # --------------------------------------------
    # META
    # --------------------------------------------

    candidates = [
        {
            "property":
            "article:published_time"
        },
        {
            "name":
            "article:published_time"
        },
        {
            "property":
            "og:published_time"
        },
        {
            "name":
            "date"
        },
        {
            "name":
            "pubdate"
        },
    ]

    for attrs in candidates:

        tag = soup.find(
            "meta",
            attrs=attrs
        )

        if (
            tag
            and tag.get("content")
        ):

            parsed = parse_date_string(
                tag["content"]
            )

            if parsed:
                return parsed

    # --------------------------------------------
    # ETIQUETAS TIME
    # --------------------------------------------

    for time_tag in soup.find_all(
        "time"
    ):

        value = (
            time_tag.get("datetime")
            or time_tag.get_text(
                " ",
                strip=True
            )
        )

        parsed = parse_date_string(
            value
        )

        if parsed:
            return parsed

    # --------------------------------------------
    # JSON-LD
    # --------------------------------------------

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        text = script.string

        if not text:
            continue

        match = re.search(
            r'"datePublished"\s*:\s*"([^"]+)"',
            text,
        )

        if match:

            parsed = parse_date_string(
                match.group(1)
            )

            if parsed:
                return parsed

    return None


# ============================================================
# EXTRAER TITULAR
# ============================================================

def extract_title(soup, fallback=""):

    h1 = soup.find("h1")

    if h1:

        title = clean_text(
            h1.get_text(
                " ",
                strip=True
            )
        )

        if title:
            return title

    # OpenGraph
    tag = soup.find(
        "meta",
        attrs={
            "property": "og:title"
        }
    )

    if (
        tag
        and tag.get("content")
    ):

        title = clean_text(
            tag["content"]
        )

        if title:
            return title

    # HTML title
    if soup.title:

        title = clean_text(
            soup.title.get_text(
                " ",
                strip=True
            )
        )

        if title:

            title = re.sub(
                r"\s*[-|]\s*20minutos.*$",
                "",
                title,
                flags=re.I,
            )

            return title

    return clean_text(
        fallback
    )


# ============================================================
# DESCRIPCIÓN
# ============================================================

def extract_description(soup):

    tag = soup.find(
        "meta",
        attrs={
            "name": "description"
        }
    )

    if (
        tag
        and tag.get("content")
    ):

        return clean_text(
            tag["content"]
        )

    tag = soup.find(
        "meta",
        attrs={
            "property": "og:description"
        }
    )

    if (
        tag
        and tag.get("content")
    ):

        return clean_text(
            tag["content"]
        )

    return ""


# ============================================================
# AUTOR
# ============================================================

def extract_author(soup):

    tag = soup.find(
        "meta",
        attrs={
            "name": "author"
        }
    )

    if (
        tag
        and tag.get("content")
    ):

        return clean_text(
            tag["content"]
        )

    return ""


# ============================================================
# ENLACES DE LA SECCIÓN
# ============================================================

def get_article_links():

    links = {}

    urls_to_check = [
        SECTION_URL
    ]

    # Probamos posibles páginas adicionales.
    for page in range(
        2,
        MAX_PAGES + 1
    ):

        urls_to_check.append(
            f"{SECTION_URL}{page}/"
        )

    for page_url in urls_to_check:

        try:

            source = download(
                page_url
            )

        except Exception as exc:

            print(
                f"No se pudo descargar "
                f"{page_url}: {exc}"
            )

            continue

        soup = BeautifulSoup(
            source,
            "lxml"
        )

        for a in soup.find_all(
            "a",
            href=True
        ):

            href = urljoin(
                BASE_URL,
                a["href"]
            )

            href = clean_url(
                href
            )

            if not valid_article_url(
                href
            ):
                continue

            title = clean_text(
                a.get_text(
                    " ",
                    strip=True
                )
            )

            if href not in links:

                links[href] = title

            else:

                # Nos quedamos con el texto más largo
                # encontrado para ese enlace.
                if (
                    len(title)
                    > len(links[href])
                ):

                    links[href] = title

    print(
        f"Enlaces únicos encontrados: "
        f"{len(links)}"
    )

    return links


# ============================================================
# LEER ARTÍCULO
# ============================================================

def get_article(
    url,
    fallback_title
):

    try:

        source = download(
            url
        )

    except Exception as exc:

        print(
            f"ERROR artículo "
            f"{url}: {exc}"
        )

        return None

    soup = BeautifulSoup(
        source,
        "lxml"
    )

    title = extract_title(
        soup,
        fallback_title
    )

    if not title:
        return None

    published = extract_date(
        soup
    )

    description = extract_description(
        soup
    )

    author = extract_author(
        soup
    )

    return {
        "title": title,
        "url": url,
        "date": published,
        "description": description,
        "author": author,
    }


# ============================================================
# RECOPILAR ARTÍCULOS
# ============================================================

def collect_articles():

    links = get_article_links()

    articles = []

    seen = set()

    for (
        url,
        fallback_title
    ) in links.items():

        article = get_article(
            url,
            fallback_title
        )

        if not article:
            continue

        guid = hashlib.sha256(
            url.encode(
                "utf-8"
            )
        ).hexdigest()

        if guid in seen:
            continue

        seen.add(
            guid
        )

        article["guid"] = guid

        articles.append(
            article
        )

    # Ordenamos por fecha.
    articles.sort(
        key=lambda x: (
            x["date"]
            or dt.datetime(
                1970,
                1,
                1,
                tzinfo=dt.timezone.utc
            )
        ),
        reverse=True,
    )

    return articles


# ============================================================
# GENERAR RSS
# ============================================================

def create_rss(articles):

    rss = ET.Element(
        "rss",
        {
            "version": "2.0"
        }
    )

    channel = ET.SubElement(
        rss,
        "channel"
    )

    ET.SubElement(
        channel,
        "title"
    ).text = (
        "20minutos - "
        "La Información - Empresas"
    )

    ET.SubElement(
        channel,
        "link"
    ).text = SECTION_URL

    ET.SubElement(
        channel,
        "description"
    ).text = (
        "Noticias de Empresas "
        "de La Información / 20minutos"
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "es"

    ET.SubElement(
        channel,
        "lastBuildDate"
    ).text = format_datetime(
        dt.datetime.now(
            dt.timezone.utc
        )
    )

    # ========================================================
    # ARTÍCULOS
    # ========================================================

    for article in articles:

        item = ET.SubElement(
            channel,
            "item"
        )

        # ====================================================
        # SOLO TITULAR
        # ====================================================

        ET.SubElement(
            item,
            "title"
        ).text = article["title"]

        # ====================================================
        # ENLACE
        # ====================================================

        ET.SubElement(
            item,
            "link"
        ).text = article["url"]

        # ====================================================
        # GUID
        # ====================================================

        guid = ET.SubElement(
            item,
            "guid",
            {
                "isPermaLink": "false"
            }
        )

        guid.text = article["guid"]

        # ====================================================
        # FECHA
        # Feedly podrá ordenar correctamente las noticias,
        # pero NO se añade la fecha al titular.
        # ====================================================

        if article["date"]:

            date_value = article["date"]

            if (
                date_value.tzinfo
                is None
            ):

                date_value = (
                    date_value.replace(
                        tzinfo=dt.timezone.utc
                    )
                )

            ET.SubElement(
                item,
                "pubDate"
            ).text = format_datetime(
                date_value
            )

        # ====================================================
        # DESCRIPCIÓN
        # ====================================================

        description_parts = []

        if article[
            "description"
        ]:

            description_parts.append(
                html.escape(
                    article[
                        "description"
                    ]
                )
            )

        if article[
            "author"
        ]:

            description_parts.append(
                "<b>Autor:</b> "
                + html.escape(
                    article[
                        "author"
                    ]
                )
            )

        if description_parts:

            ET.SubElement(
                item,
                "description"
            ).text = "<br><br>".join(
                description_parts
            )

    # ========================================================
    # GUARDAR XML
    # ========================================================

    tree = ET.ElementTree(
        rss
    )

    ET.indent(
        tree,
        space="  "
    )

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "20MINUTOS - "
        "LA INFORMACIÓN - "
        "EMPRESAS"
    )

    print(
        "=" * 60
    )

    articles = collect_articles()

    print(
        f"\nArtículos obtenidos: "
        f"{len(articles)}"
    )

    print(
        "\nÚltimos titulares:"
    )

    for article in articles[:20]:

        print(
            "- "
            + article["title"]
        )

    create_rss(
        articles
    )

    print(
        "\nRSS creada correctamente:"
    )

    print(
        OUTPUT_FILE
    )


if __name__ == "__main__":
    main()

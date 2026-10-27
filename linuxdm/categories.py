"""Filename-based destination suggestions; explicit user folders always take priority."""
from pathlib import Path
from urllib.parse import unquote, urlsplit

EXTENSIONS = {
    'Videos': 'mp4 mkv webm avi mov m4v mpg mpeg wmv flv ts m3u8 mpd',
    'Music': 'mp3 flac wav ogg opus m4a aac wma aiff alac',
    'Documents': 'pdf doc docx odt rtf txt md epub mobi xls xlsx ods csv ppt pptx odp',
    'Pictures': 'jpg jpeg png gif webp svg bmp tiff tif ico avif heic',
    'Archives': 'zip rar 7z tar gz bz2 xz zst tgz tbz2 txz',
    'Programs': 'deb rpm appimage exe msi apk flatpak flatpakref snap run sh bin iso',
}
CATEGORIES = (*EXTENSIONS, 'Other')


def detect_category(url='', filename='', kind='file'):
    if kind == 'video':
        return 'Videos'
    name = filename or unquote(urlsplit(url).path)
    suffix = Path(name).suffix.lower().lstrip('.')
    return next((category for category, extensions in EXTENSIONS.items()
                 if suffix in extensions.split()), 'Other')


def category_directory(base, category):
    if category not in CATEGORIES:
        raise ValueError('Choose a valid download category.')
    return str(Path(base).expanduser() / category)


def suggested_directory(base, url='', filename='', kind='file'):
    return category_directory(base, detect_category(url, filename, kind))

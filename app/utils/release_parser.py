from guessit import guessit

def parse_release_title(title):
    """
    Parses a release title using guessit and returns a structured dictionary
    with simplified and additional intelligent properties.
    """
    guess = guessit(title)

    # Start with a base of sanitized data
    parsed_data = {
        'quality': guess.get('screen_size'),
        'video_codec': guess.get('video_codec'),
        'source': guess.get('source'),
        'season': guess.get('season'),
        'episode': guess.get('episode'),
        'is_special': False,
        'is_season_pack': False,
    }

    # Handle language separately for robustness
    lang_value = guess.get('language')
    if lang_value:
        if isinstance(lang_value, list):
            parsed_data['language'] = ','.join([str(l) for l in lang_value])
        else:
            parsed_data['language'] = str(lang_value)
    else:
        parsed_data['language'] = None

    # Intelligent flag for season packs
    if parsed_data['season'] is not None and parsed_data['episode'] is None:
        parsed_data['is_season_pack'] = True

    # Intelligent flag for specials
    if parsed_data['season'] == 0:
        parsed_data['is_special'] = True

    if 'episode_title' in guess and isinstance(guess['episode_title'], str) and 'special' in guess['episode_title'].lower():
        parsed_data['is_special'] = True

    # A common pattern for specials is a high episode number
    if isinstance(parsed_data['episode'], int) and parsed_data['episode'] > 50:
         if parsed_data['season'] is not None: # Avoid marking movies as specials
            parsed_data['is_special'] = True

    return parsed_data

import shutil
import sys
from functools import partial
from typing import Optional, Callable
import logging
from logging.handlers import RotatingFileHandler
import time
import subprocess
from datetime import datetime, timedelta
from base64 import b64encode
import os

import requests

log = logging.getLogger('cover_display')


class TokenException(Exception):
    pass


class PlayingException(Exception):
    pass


class TokenGenerator:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self._token: Optional[str] = None
        self._expires: Optional[datetime] = None
        self.client_id: str = client_id
        self.client_secret: str = client_secret
        self.refresh_token: str = refresh_token

        # see https://developer.spotify.com/documentation/general/guides/authorization-guide/
        self.token_request: Callable = partial(
            requests.post,
            'https://accounts.spotify.com/api/token',
            data={
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token
            },
            headers={
                'Authorization': 'Basic ' + b64encode(f'{self.client_id}:{self.client_secret}'.encode()).decode()
            }
        )

    def generate_new_token(self) -> None:
        r: requests.Response = self.token_request()
        if not r.ok:
            raise TokenException(f'Could not obtain new spotify token: {r.text}')
        j = r.json()
        self._token = j['access_token']
        self._expires = datetime.now() + timedelta(seconds=int(j['expires_in'] - 100))
        log.info('Generated new access token')

    @property
    def token(self) -> str:
        if (not self._token) or (not self._expires) or (self._expires < datetime.now()):
            self.generate_new_token()
        return self._token


class CoverDisplay:
    def __init__(self, client_id, client_secret: str, refresh_token: str):
        self.display_url: Optional[str] = None
        self.display_process: Optional[str] = None
        self.token_generator: TokenGenerator = TokenGenerator(client_id, client_secret, refresh_token)
        self.temp_file = 'cover.jpg'

    def start_displaying(self):
        log.info('Start displaying cover art')
        while True:
            try:
                r: requests.Response = requests.get(
                    'https://api.spotify.com/v1/me/player/currently-playing',
                    headers={
                        'Authorization': f'Bearer {self.token_generator.token}',
                    }
                )
                if not r.ok:
                    raise PlayingException(f'Could not access now playing: {r.text}')
                j = r.json()
                display_url = j.get('item', {}).get('album', {}).get('images', [{}])[0].get('url')
                if self.display_url != display_url and display_url:
                    log.info('Update Cover')
                    image_r = requests.get(display_url, stream=True)
                    with open(self.temp_file, 'wb') as f:
                        shutil.copyfileobj(image_r.raw, f)
                    self.display_url = display_url
                    # if self.display_process:  # we need to refresh the image
                    #     self.display_process.kill()
                    # self.display_process = subprocess.Popen(['fbi', 'cover.jpg'])
                time.sleep(10)  # wait 10 secs for updates

            except TokenException as e:
                log.error(f'Could not generate a new token! We back off 10 minutes! {e}')
                time.sleep(10 * 60)
            except PlayingException as e:
                log.error(f'Could not receive current playing track! Back off 1 minute! {e}')
                time.sleep(1 * 60)
            except KeyboardInterrupt:
                log.info(f'Stop displaying')
                break
            # except Exception as e:
            #     logging.critical(f'Uncaught exception: {e} - back off 1h')
            #     time.sleep(60*60)


if __name__ == '__main__':
    # setup logging
    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh = RotatingFileHandler(
        filename='cover_display.log',
        maxBytes=1024 * 10,
    )
    fh.setFormatter(formatter)
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    log.addHandler(ch)

    log.info('Waiting 20 seconds for network')
    # time.sleep(20)
    log.info('Lets go!')
    try:
        cd = CoverDisplay(
            os.environ['SPOTIFY_CLIENT_ID'],
            os.environ['SPOTIFY_CLIENT_SECRET'],
            os.environ['SPOTIFY_REFRESH_TOKEN'],
        )
    except KeyError as e:
        msg = 'Please set the necessary environment variables ' \
              'SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN'
        log.critical(msg)
        print(msg)
        sys.exit(1)
    cd.start_displaying()

import json
import logging
import os
import sys
import time
from http import HTTPStatus
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from telebot import TeleBot

from exceptions import APIError, JSONDecodeError

load_dotenv()

# Создание логера:
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
# Создание обработчика логов:
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

# Токены:
PRACTICUM_TOKEN: Optional[str] = os.getenv('PRACTICUM')
TELEGRAM_TOKEN: Optional[str] = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID: Optional[str] = os.getenv('TELEGRAM')

# Время (в секундах) для коррекции первого запроса.
DELTA = 600
# Время (в секундах) для ожидания перед отправкой следующего запроса.
RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

# Статусы проверки работы:
HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


def check_tokens() -> bool:
    """
    Проверяет доступность обязательных переменных окружения.

    Returns:
        bool: True, если все переменные окружения доступны, иначе False.
    """
    tokens: Dict[str, Optional[str]] = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID
    }
    empty_tokens: List[Optional[str]] = [
        name for name, token in tokens.items() if not token
    ]
    if  empty_tokens:
        logging.critical(
            f'Ошибка: Отсутствуют переменные: {", ".join(empty_tokens)}.'
        )
        return False
    return True


def send_message(bot: Any, message: str) -> None:
    """
    Отправляет сообщение через указанный бот.

    Args:
        bot (Any): Экземпляр бота, через который будет отправлено сообщение.
        message (str): Текст сообщения, которое нужно отправить.

    Returns:
        None
    """
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logging.debug(f'Сообщение успешно отправлено: {message}')
    except Exception as error:
        logging.error(f'{error} ошибка отправки сообщения в телеграм.')


def get_api_answer(timestamp: int) -> Optional[Dict]:
    """
    Делает запрос к API Яндекс.Практикума и возвращает ответ в виде словаря.

    Args:
        timestamp (int): Временная метка для параметра 'from_date' запроса.

    Returns:
        Optional[Dict]: Ответ API, преобразованный в словарь, иначе None.
    """
    payload: Dict[str, int] = {'from_date': timestamp}
    status: int = HTTPStatus.OK
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=payload)
        if response.status_code != status:
            raise APIError(
                f'Ошибка, статус код '
                f'{response.status_code}: {response.text}.'
            )
        return response.json()
    except requests.exceptions.RequestException as error:
        raise APIError(f'Эндпоинт недоступен: {ENDPOINT}.')
    except json.decoder.JSONDecodeError:
        raise JSONDecodeError(
            'Ошибка преобразования ответа от сервера в json формат.'
        )


def check_response(response: Dict[str, Any]) -> Optional[Dict]:
    """
    Проверяет наличие ключа 'homework' в ответе и возвращает его значение.

    Args:
        response (Dict[str, Any]): Словарь, содержащий данные ответа.

    Returns:
        Optional[List[Any]]: Список домашнего задания,
        если ключ 'homework' существует, иначе None.
    """
    if not isinstance(response, dict):
        raise TypeError(
            f'Ожидается dict, получен тип данных:{type(response)}.'
        )
    homework: List[Any] = response.get('homeworks')
    if homework is None:
        raise ValueError('В словаре отсутствует ключ "homeworks".')
    if not isinstance(homework, list):
        raise TypeError(
            f'Ожидается list, получен тип данных:{type(homework)}.'
        )
    if not homework:
        logging.debug('Работа еще не проверена.')
    else:
        return homework[0]


def parse_status(homework: Dict) -> Optional[str]:
    """
    Извлекает из полученного ответа название ДЗ и его статус.

    Args:
        homework (Dict): Список, содержащий информацию о домашней работе.

    Returns:
        Optional[str]: Сообщение о статусе проверки работы, иначе None.
    """
    homework_name: str = homework.get('homework_name')
    status: str = homework.get('status')
    verdict: str = HOMEWORK_VERDICTS.get(status)
    if homework_name is None or status is None or verdict is None:
        raise ValueError('Отсутствуют данные о домашней работе.')
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    if not check_tokens():
        sys.exit('Прекращение работы: отсутствие переменной окружения.')
    # Флаги проверки, для избежания повторной отправки сообщений с ошибкой.
    work_flag = False
    api_flag = False
    # Объявление экземпляра бота.
    bot = TeleBot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time()) - DELTA
    while True:
        try:
            response = get_api_answer(timestamp)
            homework = check_response(response)
            if homework:
                message = parse_status(homework)
                if message:
                    send_message(bot, message)
                    work_flag = False
                else:
                    logging.debug('В ответе отсутствует новый статус.')
            # Новый временной штамп - время получения предыдущего ответа.
            timestamp = response.get('current_date', timestamp)
            api_flag = False
        except (APIError, JSONDecodeError) as error:
            logging.critical(error)
            if not api_flag:
                send_message(bot, error)
                api_flag = True
        except (TypeError, ValueError, Exception) as error:
            logging.error(error)
            if not work_flag:
                send_message(bot, error)
                work_flag = True
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()

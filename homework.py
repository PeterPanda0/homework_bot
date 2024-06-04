from http import HTTPStatus

import logging
import os
import requests
import sys
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from telebot import TeleBot

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

PRACTICUM_TOKEN: str = os.getenv('PRACTICUM')
TELEGRAM_TOKEN: str = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID: str = os.getenv('TELEGRAM')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


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
    for token in (PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID):
        if not token:
            logging.critical(
                f'Ошибка: Отсутствует переменная окружения {token}.'
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
    payload = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=payload)
        status = HTTPStatus.OK
        if response.status_code != status:
            logging.error(f'Ошибка {response.status_code}: {response.text}')
            raise Exception('Ошибочный статус код.')
        return response.json()
    except requests.exceptions.RequestException as error:
        logging.error(f'Эндпоинт недоступен: {ENDPOINT}. {error}')


def check_response(response: Dict[str, Any]) -> Optional[Dict]:
    """
    Проверяет наличие ключа 'homework' в ответе и возвращает его значение.

    Args:
        response (Dict[str, Any]): Словарь, содержащий данные ответа.

    Returns:
        Optional[List[Any]]: Список домашнего задания,
        если ключ 'homework' существует, иначе None.
    """
    try:
        homework: List[Any] = response['homeworks']
        if not isinstance(homework, list):
            raise TypeError('Данные в ответе API не являются списком.')
        if not homework:
            logging.debug('Работа еще не проверена.')
            return homework
        return homework[0]
    except KeyError as error:
        logging.error(f'Ошибка с получением данных о статусе ДЗ. {error}.')
        raise KeyError(f'Отсутствует ключ {error} в ответе API')
    except TypeError as type_error:
        logging.error(f'Ошибка в получении данных о статусе ДЗ {type_error}.')
        raise TypeError('Данные в ответе API не соответствуют ожиданиям.')
    except Exception as error:
        logging.error(f'Ошибка с получением данных о статусе ДЗ. {error}.')


def parse_status(homework: Dict) -> Optional[str]:
    """
    Извлекает из полученного ответа название ДЗ и его статус.

    Args:
        homework (Dict): Список, содержащий информацию о домашней работе.

    Returns:
        Optional[str]: Сообщение о статусе проверки работы, иначе None.
    """
    try:
        homework_name: str = homework['homework_name']
    except KeyError:
        raise KeyError('Отсутствует ключ "homework_name" в ответе API.')
    try:
        status: str = homework.get('status')
        verdict: str = HOMEWORK_VERDICTS.get(status)
        if status is None or verdict is None:
            raise ValueError('Отсутствуют данные о домашней работе.')
        return f'Изменился статус проверки работы "{homework_name}". {verdict}'
    except KeyError as key_error:
        logging.error(f'Ошибка в запрашиваемом значении ключа {key_error}.')
    except ValueError as ve:
        logging.error(f'Ошибка в значении данных о ДЗ {ve}.')
        raise ve
    except Exception as error:
        logging.error(f'Ошибка с получением данных о проверке ДЗ. {error}')


def main():
    """Основная логика работы бота."""
    if not check_tokens():
        sys.exit('Прекращение работы: отсутствие переменной окружения.')
    # Флаги проверки, для избежания повторной отправки сообщений с ошибкой.
    work_flag = False
    api_flag = False
    # Флаг проверки, для избежания повторной отправки неизмененного статуса.
    previous_message = None
    # Объявление экземпляра бота.
    bot = TeleBot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    while True:
        work_status = get_api_answer(timestamp)
        if work_status:
            homework = check_response(work_status)
            if homework:
                message = parse_status(homework)
                if message and message != previous_message:
                    send_message(bot, message)
                    previous_message = message
                    work_flag = False
                else:
                    logging.debug('В ответе отсутствует новый статус.')
            # Явная проверка, чтобы пользователь не получал сообщение
            # о проблеме, если переменная homework пустой list.
            elif not isinstance(homework, list):
                if not work_flag:
                    send_message(bot, 'Проблема с получением статуса ДЗ.')
                    work_flag = True
        else:
            if not api_flag:
                send_message(bot, 'Проблема с получением API.')
                api_flag = True
        api_flag = False
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()

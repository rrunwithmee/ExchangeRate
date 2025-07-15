
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import requests
from datetime import datetime

app = FastAPI()
templates = Jinja2Templates(directory="templates")

API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"


def get_currency_list(rates_data):
    currencies = []
    for code, data in rates_data['Valute'].items():
        currencies.append({
            "code": code,
            "name": data['Name'],
            "value": data['Value'],
            "nominal": data['Nominal']
        })
    return sorted(currencies, key=lambda x: x['name'])


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    try:
        rates_data = get_current_rates()
        currencies = get_currency_list(rates_data)
        return templates.TemplateResponse("index.html", {
            "request": request,
            "rates": rates_data,
            "currencies": currencies,
            "conversion_result": None
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка на главной странице: {str(e)}")


def get_current_rates():
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения данных: {str(e)}")


@app.get("/convert", response_class=HTMLResponse)
async def convert_currency(
    request: Request,
    amount: float = Query(..., gt=0),
    from_currency: str = Query(...),
    to_currency: str = Query(...)
):
    try:
        rates_data = get_current_rates()
        currencies = get_currency_list(rates_data)

        # Проверка наличия валют в данных
        if from_currency not in rates_data['Valute'] or to_currency not in rates_data['Valute']:
            raise HTTPException(status_code=400, detail="Неверный код валюты")

        # Получаем данные для валют
        from_data = rates_data['Valute'][from_currency]
        to_data = rates_data['Valute'][to_currency]

        # Рассчитываем курс с учетом номинала
        from_rate = from_data['Value'] / from_data['Nominal']
        to_rate = to_data['Value'] / to_data['Nominal']

        # Конвертируем сумму
        converted_amount = (amount * from_rate) / to_rate

        # Форматируем результат
        conversion_result = {
            'amount': amount,
            'from_currency': from_currency,
            'from_name': from_data['Name'],
            'converted_amount': converted_amount,
            'to_currency': to_currency,
            'to_name': to_data['Name'],
            'rate': to_rate / from_rate
        }

        return templates.TemplateResponse("index.html", {
            "request": request,
            "rates": rates_data,
            "currencies": currencies,
            "conversion_result": conversion_result
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка конвертации: {str(e)}")


@app.get("/historical", response_class=HTMLResponse)
async def historical_rates(
        request: Request,
        date: str = Query(None),
        amount: float = Query(None),
        from_currency: str = Query(None),
        to_currency: str = Query(None)
):
    try:
        if not date:
            raise HTTPException(status_code=400, detail="Не указана дата")

        try:
            rates_data = get_historical_rates(date)
        except HTTPException as e:
            if e.status_code == 404:
                return templates.TemplateResponse("index.html", {
                    "request": request,
                    "rates": {"Date": datetime.now().strftime("%Y-%m-%d")},
                    "currencies": [],
                    "selected_date": date,
                    "historical_error": e.detail
                })
            raise

        currencies = get_currency_list(rates_data)

        # Проверка: если указана хотя бы одна валюта, но не указана сумма
        if (from_currency or to_currency) and not amount:
            return templates.TemplateResponse("index.html", {
                "request": request,
                "rates": rates_data,
                "currencies": currencies,
                "selected_date": date,
                "historical_error": "Для конвертации валют необходимо указать сумму"
            })

        # Проверка: если указана только одна валюта
        if (from_currency and not to_currency) or (not from_currency and to_currency):
            return templates.TemplateResponse("index.html", {
                "request": request,
                "rates": rates_data,
                "currencies": currencies,
                "selected_date": date,
                "historical_error": "Для конвертации необходимо указать обе валюты"
            })

        conversion_result = None
        if amount and from_currency and to_currency:
            if from_currency == to_currency:
                conversion_result = {
                    'amount': amount,
                    'from_currency': from_currency,
                    'from_name': rates_data['Valute'][from_currency]['Name'],
                    'converted_amount': amount,
                    'to_currency': to_currency,
                    'to_name': rates_data['Valute'][to_currency]['Name'],
                    'rate': 1.0,
                    'historical_date': date
                }
            else:
                from_data = rates_data['Valute'][from_currency]
                to_data = rates_data['Valute'][to_currency]
                from_rate = from_data['Value'] / from_data['Nominal']
                to_rate = to_data['Value'] / to_data['Nominal']
                converted_amount = (amount * from_rate) / to_rate

                conversion_result = {
                    'amount': amount,
                    'from_currency': from_currency,
                    'from_name': from_data['Name'],
                    'converted_amount': converted_amount,
                    'to_currency': to_currency,
                    'to_name': to_data['Name'],
                    'rate': to_rate / from_rate,
                    'historical_date': date
                }

        return templates.TemplateResponse("index.html", {
            "request": request,
            "rates": rates_data,
            "currencies": currencies,
            "conversion_result": conversion_result,
            "selected_date": date
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения исторических данных: {str(e)}")


@app.get("/historical/{date}")
def get_historical_rates(date: str):
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты. Используйте YYYY-MM-DD.")

    historical_url = f"https://www.cbr-xml-daily.ru/archive/{date_obj.year}/{date_obj.month:02d}/{date_obj.day:02d}/daily_json.js"
    try:
        response = requests.get(historical_url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Данные за эту дату не найдены")
        raise HTTPException(status_code=500, detail=f"Ошибка при получении данных: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Ошибка соединения: {str(e)}")
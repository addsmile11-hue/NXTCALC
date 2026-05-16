from flask import Flask, request
import requests

app = Flask(__name__)

TOKEN = "8700029074:AAEHRkhgm5GYNP5eO5m-5Fqpr6cg_g7IgdQ"
CHAT_ID = "7107327530"

headers = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
}

TOP_10_STOCKS = {
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "005380": "현대차", "068270": "셀트리온",
    "000270": "기아", "105560": "KB금융", "055550": "신한지주", "005490": "POSCO홀딩스"
}

def parse_korean_cap(val_str):
    if not val_str: return 0.0
    val_str = str(val_str).replace(',', '').strip()
    jo, eok = 0, 0
    if '조' in val_str:
        parts = val_str.split('조')
        jo = float(parts[0].strip())
        if len(parts) > 1 and '억' in parts[1]:
            eok_str = parts[1].replace('억', '').strip()
            eok = float(eok_str) if eok_str else 0.0
    elif '억' in val_str:
        eok = float(val_str.replace('억', '').strip())
    return (jo * 10000) + eok

def calculate_nxt_kospi():
    try:
        # 1. 최근 250일치 코스피 종가 데이터 가져오기 (pageSize=250으로 확장)
        kospi_url = "https://m.stock.naver.com/api/index/KOSPI/price?pageSize=250"
        kospi_data = requests.get(kospi_url, headers=headers).json()
        
        kospi_latest = float(kospi_data[0]['closePrice'].replace(',', ''))  # 가장 최근 거래일 종가
        kospi_previous = float(kospi_data[1]['closePrice'].replace(',', '')) # 그 전 거래일 종가

        # 2. 기준일 자동 판별 알고리즘 (NXT 등락률 기준가 역산)
        anchor_url = "https://m.stock.naver.com/api/stock/005930/basic"
        anchor_res = requests.get(anchor_url, headers=headers).json()
        
        krx_close = float(str(anchor_res.get('closePrice', '0')).replace(',', ''))
        over_info = anchor_res.get('overMarketPriceInfo')
        
        use_previous_kospi = False
        if over_info and over_info.get('overPrice'):
            nxt_price = float(str(over_info['overPrice']).replace(',', ''))
            nxt_return = float(over_info['fluctuationsRatio']) / 100
            
            if nxt_return != -1.0:
                calculated_base_price = nxt_price / (1 + nxt_return)
                if abs(calculated_base_price - krx_close) > (krx_close * 0.01):
                    use_previous_kospi = True

        # 최종 매칭할 코스피 기준 지수 및 날짜 결정
        if use_previous_kospi:
            base_kospi = kospi_previous
            base_date_raw = kospi_data[1]['localTradedAt']
        else:
            base_kospi = kospi_latest
            base_date_raw = kospi_data[0]['localTradedAt']

        # 기준 날짜 포맷팅 (YYYY-MM-DD -> YYYY년MM월DD일)
        date_parts = base_date_raw.split('-')
        formatted_base_date = f"{date_parts[0]}년{date_parts[1]}월{date_parts[2]}일"

        # 3. 10개 종목 데이터 수집 및 계산
        stock_data_list = []
        total_market_cap = 0

        for code, name in TOP_10_STOCKS.items():
            url = f"https://m.stock.naver.com/api/stock/{code}/basic"
            res = requests.get(url, headers=headers).json()
            
            if 'marketCap' in res and res['marketCap']:
                market_cap = float(res['marketCap'])
            elif 'marketValue' in res and res['marketValue']:
                market_cap = parse_korean_cap(res['marketValue'])
            else:
                market_cap = 1.0
                
            total_market_cap += market_cap
            
            over_info = res.get('overMarketPriceInfo')
            if over_info and over_info.get('overPrice'):
                nxt_return = float(over_info['fluctuationsRatio']) / 100
                has_nxt = True
            else:
                nxt_return = 0.0
                has_nxt = False
                
            stock_data_list.append({
                "name": name, "market_cap": market_cap, "nxt_return": nxt_return, "has_nxt": has_nxt
            })

        total_weighted_return = 0.0
        stock_details = ""
        
        for s in stock_data_list:
            weight = s['market_cap'] / total_market_cap if total_market_cap else 0.0
            total_weighted_return += s['nxt_return'] * weight
            
            if s['has_nxt']:
                stock_details += f"🔹 {s['name']}: {s['nxt_return']*100:+.2f}%\n"

        # NXT 예상 지수 산출
        nxt_kospi = base_kospi * (1 + total_weighted_return)
        change_percent = total_weighted_return * 100

        # 4. [신규 기능] 250일 최고가 및 실시간 MDD 동적 계산
        historical_prices = [float(item['closePrice'].replace(',', '')) for item in reversed(kospi_data)]
        all_prices = historical_prices + [nxt_kospi]  # 과거 데이터 끝에 현재 예상 지수 병합

        # 250일 최고가 및 해당 날짜 검색
        peak_price = 0.0
        peak_date = ""
        for item in kospi_data:
            p = float(item['closePrice'].replace(',', ''))
            if p > peak_price:
                peak_price = p
                peak_date = item['localTradedAt']

        # 만약 현재 NXT 예상 지수가 250일 전고점을 돌파했다면 업데이트
        if nxt_kospi > peak_price:
            peak_price = nxt_kospi
            formatted_peak_date = " [현재(NXT)]"
        else:
            p_parts = peak_date.split('-')
            formatted_peak_date = f" [{p_parts[0]}년{p_parts[1]}월{p_parts[2]}일]"

        # 시계열 기반 고점 대비 최대 낙폭(MDD) 계산
        max_dd = 0.0
        current_peak = 0.0
        for price in all_prices:
            if price > current_peak:
                current_peak = price
            if current_peak > 0:
                dd = (price - current_peak) / current_peak
                if dd < max_dd:
                    max_dd = dd
        mdd_percent = max_dd * 100

        # 요청하신 형태로 브리핑 문구 조립
        msg = (
            f"📊 [NXT 기반 코스피 예상 지수]\n\n"
            f"▪️ [{formatted_base_date}] 기준 정규장 종가: {base_kospi:,.2f}\n"
            f"▪️ 현재 NXT 예상 지수: {nxt_kospi:,.2f}\n"
            f"▪️ 예상 변동률: {change_percent:+.2f}%\n"
            f"▪️ 250일 최고가 : {peak_price:,.2f}{formatted_peak_date}\n"
            f"▪️ MDD : {mdd_percent:.2f}%\n\n"
            f"🔥 [NXT 주요 변동 종목]\n"
            f"{stock_details if stock_details else '움직임이 있는 대형주가 없습니다.'}"
        )
        return msg
    except Exception as e:
        return f"❌ 지수 계산 중 오류 발생: {e}"

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    requests.post(url, json=payload)

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    update = request.get_json()
    if "message" in update:
        text = update["message"].get("text", "")
        if text == "/check":
            result_msg = calculate_nxt_kospi()
            send_telegram_message(result_msg)
    return "OK", 200

@app.route('/')
def home():
    return "NXT KOSPI BOT SERVER IS RUNNING!"

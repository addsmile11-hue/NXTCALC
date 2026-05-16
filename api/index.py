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
        # 1. 최근 2일치 코스피 종가 데이터 가져오기 (pageSize=2)
        kospi_url = "https://m.stock.naver.com/api/index/KOSPI/price?pageSize=2"
        kospi_data = requests.get(kospi_url, headers=headers).json()
        kospi_latest = float(kospi_data[0]['closePrice'].replace(',', ''))  # 가장 최근 거래일 종가 (예: 금요일)
        kospi_previous = float(kospi_data[1]['closePrice'].replace(',', '')) # 그 전 거래일 종가 (예: 목요일)

        # 2. 기준일 자동 판별 알고리즘 (삼성전자를 앵커로 활용)
        # 현재 NXT 등락률이 '가장 최근 종가' 기준인지 '그 전 거래일 종가' 기준인지 역산하여 찾아냅니다.
        anchor_url = "https://m.stock.naver.com/api/stock/005930/basic"
        anchor_res = requests.get(anchor_url, headers=headers).json()
        
        krx_close = float(str(anchor_res.get('closePrice', '0')).replace(',', ''))
        over_info = anchor_res.get('overMarketPriceInfo')
        
        use_previous_kospi = False
        if over_info and over_info.get('overPrice'):
            nxt_price = float(str(over_info['overPrice']).replace(',', ''))
            nxt_return = float(over_info['fluctuationsRatio']) / 100
            
            if nxt_return != -1.0:
                # 등락률 공식으로 역산한 기준가
                calculated_base_price = nxt_price / (1 + nxt_return)
                
                # 역산한 기준가가 현재 정규장 종가와 차이가 크다면, 
                # 현재 NXT가 '전일 종가(목요일)'를 기준으로 계산 중인 상태(주말/장마감 세션)임을 의미합니다.
                if abs(calculated_base_price - krx_close) > (krx_close * 0.01):
                    use_previous_kospi = True

        # 최종 매칭할 코스피 기준 지수 결정
        base_kospi = kospi_previous if use_previous_kospi else kospi_latest

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

        # 산출된 가중 등락률을 알맞은 기준 코스피 지수에 적용
        nxt_kospi = base_kospi * (1 + total_weighted_return)
        change_percent = total_weighted_return * 100

        # 결과 메시지 양식
        msg = (
            f"📊 [NXT 기반 코스피 예상 지수]\n\n"
            f"▪️ 기준 정규장 종가: {base_kospi:,.2f}\n"
            f"▪️ 현재 NXT 예상 지수: {nxt_kospi:,.2f}\n"
            f"▪️ 예상 변동률: {change_percent:+.2f}%\n\n"
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

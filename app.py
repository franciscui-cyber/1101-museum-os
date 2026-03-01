from flask import Flask, render_template_string
import pandas as pd
import gspread

app = Flask(__name__)

# 구글 시트 데이터 로드 (pandas 활용)
def get_data():
    gc = gspread.service_account(filename='credentials.json')
    sh = gc.open("데이터세그니모시").sheet1
    return pd.DataFrame(sh.get_all_records())

@app.route('/')
def index():
    df = get_data()
    # 웹페이지에 표를 출력하기 위한 간단한 HTML 구성
    return render_template_string("<h1>1101 MUSEUM 현황</h1>{{ table | safe }}", table=df.to_html())

if __name__ == '__main__':
    print("서버가 시작되었습니다: http://127.0.0.1:5000")
    app.run(port=5000)
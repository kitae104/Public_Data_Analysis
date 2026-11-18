# -*- coding: utf-8 -*-
"""
초보자 추천 주제용 공공데이터 자동 다운로드 스크립트

사용법 (Windows PowerShell / 명령 프롬프트):
    pip install requests
    python download_public_data.py              # 기본 세트 (작은 파일 위주, 약 100MB)
    python download_public_data.py --big        # 상가정보(약 350MB), 추정매출(ZIP) 포함
    python download_public_data.py --only subway,population

기상청 ASOS(날씨) API까지 받으려면 공공데이터포털 인증키(Decoding 키)를 환경변수로 넣으세요.
    set DATA_GO_KR_KEY=발급받은_디코딩_인증키        (명령 프롬프트)
    $env:DATA_GO_KR_KEY="발급받은_디코딩_인증키"     (PowerShell)

파일은 이 스크립트 옆의 data/ 폴더에 주제별로 저장됩니다.
공공데이터 CSV는 대부분 CP949(EUC-KR) 인코딩입니다. --utf8 옵션을 주면 UTF-8 사본(_utf8.csv)도 만듭니다.
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import requests

BASE = Path(__file__).resolve().parent / "data"
UA = {"User-Agent": "Mozilla/5.0 (public-data-tutorial downloader)"}

# ---------------------------------------------------------------------------
# 서울 열린데이터광장: 데이터셋 페이지의 파일 목록에서 파일명 패턴으로 골라 내려받음
# ---------------------------------------------------------------------------
SEOUL_PAGE = "https://data.seoul.go.kr/dataList/{inf_id}/{tab}/1/datasetView.do"
SEOUL_DOWN = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false"


def seoul_files(sess, inf_id, tab):
    html = sess.get(SEOUL_PAGE.format(inf_id=inf_id, tab=tab), timeout=60).text
    # 파일 다운로드용 폼(frmFile) 안의 infSeq 값 (Open API 폼의 infSeq와 다를 수 있음)
    form = re.search(r'<form name="frmFile".*?</form>', html, re.S)
    m = re.search(r'name="infSeq"\s+value="(\d+)"', form.group(0)) if form else None
    inf_seq = m.group(1) if m else "1"
    # 예: <a href="javascript:downloadFile('27');" title="파일명.csv">
    files = re.findall(r'<a href="javascript:downloadFile\(\'(\d+)\'\);?"\s+title="([^"]+)"', html)
    return inf_seq, [(s, n.strip()) for s, n in files]


def seoul_download(sess, inf_id, tab, pattern, outdir, limit=None):
    inf_seq, files = seoul_files(sess, inf_id, tab)
    picked = [(s, n) for s, n in files if re.search(pattern, n)]
    if limit:
        picked = picked[:limit]
    if not picked:
        print(f"  ! {inf_id}: '{pattern}'에 맞는 파일을 찾지 못했습니다. 페이지에서 직접 받아 주세요:")
        print(f"    {SEOUL_PAGE.format(inf_id=inf_id, tab=tab)}")
        return
    for seq, name in picked:
        target = outdir / name
        if target.exists() and target.stat().st_size > 0:
            print(f"  = 이미 있음: {name}")
            continue
        data = {"infId": inf_id, "seqNo": "", "seq": seq, "infSeq": inf_seq}
        r = sess.post(SEOUL_DOWN, data=data, timeout=600, stream=True,
                      headers={"Referer": SEOUL_PAGE.format(inf_id=inf_id, tab=tab)})
        save_stream(r, target)


# ---------------------------------------------------------------------------
# 공공데이터포털(data.go.kr) 파일데이터: 로그인 없이 받을 수 있는 파일
# ---------------------------------------------------------------------------
def datagokr_download(sess, pk, outdir):
    page = f"https://www.data.go.kr/data/{pk}/fileData.do"
    html = sess.get(page, timeout=60).text
    m = re.search(r"fn_fileDataDown\('(\d+)',\s*'([^']+)',\s*'([^']*)',\s*'(\d+)'", html)
    if not m:
        print(f"  ! {pk}: 다운로드 정보를 찾지 못했습니다. 페이지에서 직접 받아 주세요: {page}")
        return
    _, detail_pk, _, sn = m.groups()
    info = sess.post("https://www.data.go.kr/tcs/dss/selectFileDataDownload.do",
                     data={"publicDataDetailPk": detail_pk, "publicDataPk": pk, "atchFileId": "",
                           "fileDetailSn": sn, "publicDataTyCode": "PR0051"},
                     headers={"Referer": page}, timeout=60).json()
    atch = info.get("atchFileId")
    name = (info.get("fileDataRegistVO") or {}).get("orginlFileNm") or f"{pk}.csv"
    if not atch:
        print(f"  ! {pk}: 파일 ID를 받지 못했습니다(외부 링크형 데이터일 수 있음). 페이지에서 직접 받아 주세요: {page}")
        return
    target = outdir / name
    if target.exists() and target.stat().st_size > 0:
        print(f"  = 이미 있음: {name}")
        return
    r = sess.get(f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={atch}&fileDetailSn={sn}",
                 headers={"Referer": page}, timeout=900, stream=True)
    save_stream(r, target)


# ---------------------------------------------------------------------------
# 기상청 ASOS 일자료 (공공데이터포털 Open API, 인증키 필요)
# ---------------------------------------------------------------------------
def asos_daily(sess, outdir, stn="108", start="20250101", end="20260630"):
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        print("  - DATA_GO_KR_KEY가 없어 ASOS API는 건너뜁니다. (가이드의 '기상자료개방포털에서 직접 받기'를 참고)")
        return
    import csv
    url = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
    rows, s = [], start
    # API는 한 번에 최대 999행, 기간을 1년 단위로 나눠 요청
    while s <= end:
        e = min(end, f"{s[:4]}1231")
        page = 1
        while True:
            params = {"serviceKey": key, "pageNo": page, "numOfRows": 999, "dataType": "JSON",
                      "dataCd": "ASOS", "dateCd": "DAY", "startDt": s, "endDt": e, "stnIds": stn}
            j = sess.get(url, params=params, timeout=60).json()
            body = j.get("response", {}).get("body", {})
            items = (body.get("items") or {}).get("item", [])
            rows.extend(items)
            if page * 999 >= int(body.get("totalCount", 0)):
                break
            page += 1
        s = f"{int(s[:4]) + 1}0101"
        time.sleep(0.3)
    if not rows:
        print("  ! ASOS 응답이 비어 있습니다. 인증키(Decoding 키)와 활용신청 승인 여부를 확인하세요.")
        return
    target = outdir / f"ASOS_일자료_{stn}_{start}_{end}.csv"
    with open(target, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  + 저장: {target.name} ({len(rows)}행)")


# ---------------------------------------------------------------------------
def save_stream(r, target):
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "text/html" in ctype:
        print(f"  ! {target.name}: 파일 대신 웹페이지가 왔습니다. 포털에서 직접 받아 주세요.")
        return
    cd = r.headers.get("content-disposition", "")
    m = re.search(r'filename="?([^";]+)"?', cd)
    if m and target.suffix == "":
        target = target.with_name(unquote(m.group(1)))
    tmp = target.with_suffix(target.suffix + ".part")
    total = 0
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1024 * 256):
            f.write(chunk)
            total += len(chunk)
    tmp.replace(target)
    print(f"  + 저장: {target.name} ({total / 1e6:.1f} MB)")


def make_utf8_copies(folder):
    for p in folder.rglob("*.csv"):
        if p.name.endswith("_utf8.csv"):
            continue
        raw = p.read_bytes()
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            continue
        p.with_name(p.stem + "_utf8.csv").write_text(text, encoding="utf-8-sig")


TOPICS = {
    # 주제 1: 가장 붐비는 지하철역
    "subway": ("01_지하철_승하차", lambda s, d: seoul_download(
        s, "OA-12914", "S", r"CARD_SUBWAY_MONTH_2026(07|08|09|10)\.csv", d)),
    # 주제 2: 우리동네 연령 구성
    "population": ("02_주민등록인구", lambda s, d: datagokr_download(s, "15097972", d)),
    # 주제 4: 비 오는 날 따릉이
    "bike": ("04_따릉이_날씨", lambda s, d: seoul_download(
        s, "OA-14994", "F", r"일별 대여건수_(25\.1-6|25\.7-12|26\.1-6)\.csv", d)),
    "weather": ("04_따릉이_날씨", lambda s, d: asos_daily(s, d)),
    # 주제 5: 미세먼지와 지하철
    "air": ("05_미세먼지_지하철", lambda s, d: seoul_download(
        s, "OA-23044", "S", r"air_monitor_2026(07|08|09|10)\.csv", d)),
    # 주제 7: 동네 군집화용 출생 데이터(보조)
    "birth": ("07_동네군집화", lambda s, d: datagokr_download(s, "15099161", d)),
}
BIG_TOPICS = {
    # 주제 3: 우리동네 카페 수 (전국 상가정보 ZIP, 약 350MB)
    "stores": ("03_상가정보", lambda s, d: datagokr_download(s, "15083033", d)),
    # 주제 6: 동네별 업종 매출 (2025년 ZIP)
    "sales": ("06_추정매출", lambda s, d: seoul_download(
        s, "OA-22175", "A", r"추정매출-행정동\)_2025년\.zip", d)),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--big", action="store_true", help="대용량 파일(상가정보, 추정매출)도 받기")
    ap.add_argument("--only", help="쉼표로 구분한 주제 키만 받기: " + ",".join([*TOPICS, *BIG_TOPICS]))
    ap.add_argument("--utf8", action="store_true", help="CSV의 UTF-8 사본도 만들기")
    a = ap.parse_args()

    topics = dict(TOPICS)
    if a.big:
        topics.update(BIG_TOPICS)
    if a.only:
        keys = [k.strip() for k in a.only.split(",")]
        topics = {k: v for k, v in {**TOPICS, **BIG_TOPICS}.items() if k in keys}

    sess = requests.Session()
    sess.headers.update(UA)
    for key, (folder, fn) in topics.items():
        out = BASE / folder
        out.mkdir(parents=True, exist_ok=True)
        print(f"[{key}] -> {out}")
        try:
            fn(sess, out)
        except Exception as e:  # 한 주제가 실패해도 나머지는 계속
            print(f"  ! 실패: {e}")
    if a.utf8:
        make_utf8_copies(BASE)
    print("\n완료. 받지 못한 항목은 가이드 문서의 '직접 받기' 절차를 따라 주세요.")


if __name__ == "__main__":
    sys.exit(main())

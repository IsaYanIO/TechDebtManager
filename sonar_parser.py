import requests
import json
import time

# --- НАСТРОЙКИ ---
SONAR_URL = "http://localhost:9000"
SONAR_TOKEN = "Токен проекта/пользователя"
PROJECT_KEY = "Ключ проекта"
auth = (SONAR_TOKEN, "")

# ========== 1. СБОР МЕТРИК (как раньше) ==========
def get_all_metrics_definitions():
    all_metrics = []
    page = 1
    while True:
        r = requests.get(f"{SONAR_URL}/api/metrics/search", params={"p": page, "ps": 500}, auth=auth)
        r.raise_for_status()
        data = r.json()
        all_metrics.extend(data.get("metrics", []))
        if len(all_metrics) >= data.get("total", 0):
            break
        page += 1
        time.sleep(0.1)
    return all_metrics

def get_project_measures(metric_keys):
    all_measures = {}
    for i in range(0, len(metric_keys), 100):
        chunk = metric_keys[i:i+100]
        r = requests.get(f"{SONAR_URL}/api/measures/component",
                         params={"component": PROJECT_KEY, "metricKeys": ",".join(chunk)},
                         auth=auth)
        r.raise_for_status()
        for m in r.json().get("component", {}).get("measures", []):
            all_measures[m["metric"]] = m.get("value")
        time.sleep(0.1)
    return all_measures

# ========== 2. СБОР ISSUES ==========
def get_project_issues():
    """Забирает все issues проекта с пагинацией (макс. 500 на страницу)."""
    all_issues = []
    page = 1
    while True:
        r = requests.get(f"{SONAR_URL}/api/issues/search",
                         params={"componentKeys": PROJECT_KEY, "p": page, "ps": 500, "resolved": "false"},
                         auth=auth)
        r.raise_for_status()
        data = r.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)
        if len(all_issues) >= data.get("total", 0) or not issues:
            break
        page += 1
        time.sleep(0.1)
    print(f"🐞 Найдено issues: {len(all_issues)}")
    return all_issues

# ========== 3. ОБЪЕДИНЕНИЕ И СОХРАНЕНИЕ ==========
def main():
    print("🚀 Сбор данных из SonarQube...")
    definitions = get_all_metrics_definitions()
    measures = get_project_measures([m["key"] for m in definitions])
    
    full_metrics = []
    for m in definitions:
        full_metrics.append({
            "key": m.get("key"),
            "name": m.get("name"),
            "description": m.get("description"),
            "domain": m.get("domain"),
            "type": m.get("type"),
            "direction": m.get("direction"),
            "value": measures.get(m.get("key"))
        })
    
    issues = get_project_issues()
    
    output = {
        "project_key": PROJECT_KEY,
        "sonar_url": SONAR_URL,
        "metrics": full_metrics,
        "issues": issues
    }
    
    with open("sonar_full_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)
    
    print("💾 Данные сохранены в sonar_full_data.json")

if __name__ == "__main__":
    main()

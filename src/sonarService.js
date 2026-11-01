// src/sonarService.js

// Замени на URL твоего SonarQube (например, http://localhost:9000)
const SONAR_URL = 'http://localhost:9000'; 

export const fetchMetrics = async (projectKey, token) => {
  // Метрики, которые мы хотим получить: 
  // code_smells - количество "запахов" кода
  // coverage - покрытие тестами
  // complexity - сложность
  // ncloc - количество строк кода (Non-Commenting Lines of Code)
  const metricKeys = 'code_smells,coverage,complexity,ncloc';
  
  const url = `${SONAR_URL}/api/measures/component?component=${projectKey}&metricKeys=${metricKeys}`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Ошибка HTTP: ${response.status}`);
    }

    const data = await response.json();
    return data.component.measures; // Возвращаем массив метрик
  } catch (error) {
    console.error("Ошибка при запросе к SonarQube:", error);
    throw error;
  }
};
// Разбор ответа GigaChat из data/gigachat_explanations.txt.
// GigaChat отвечает в свободной форме, поэтому парсер терпим к формулировкам
// и всегда возвращает исходный текст — его можно показать как есть.

const TYPE_LABELS = {
  BUG: 'Баг',
  CODE_SMELL: 'Код-смелл',
  VULNERABILITY: 'Уязвимость',
  SECURITY_HOTSPOT: 'Хотспот безопасности',
};

export const LEVELS = {
  critical: { label: 'Критично', weight: 0 },
  high: { label: 'Высоко', weight: 1 },
  medium: { label: 'Средне', weight: 2 },
  low: { label: 'Низко', weight: 3 },
};

const LOCATION_RE = /^(?<type>[A-Za-z_]+)\s+(?:в|in)\s+(?<file>[^\s:]+):(?<line>\d+)/i;

function cleanText(value) {
  return (value || '')
    .replace(/\r/g, '')
    .replace(/\*/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function parseLocation(header) {
  const match = header.match(LOCATION_RE);
  if (!match?.groups) return null;
  return {
    type: match.groups.type.toUpperCase(),
    file: match.groups.file,
    line: Number(match.groups.line),
  };
}

function detectSectionNumber(line) {
  const numbered = line.match(/^###\s*(\d+)/);
  if (numbered && [1, 2, 3].includes(Number(numbered[1]))) {
    return Number(numbered[1]);
  }
  if (/важност|ранжир|приоритет/i.test(line)) return 2;
  if (/рекомендац/i.test(line)) return 3;
  if (/объясн/i.test(line)) return 1;
  return null;
}

function splitSections(text) {
  const sections = { 1: [], 2: [], 3: [] };
  let current = null;

  for (const line of text.split('\n')) {
    if (/^###\s/.test(line)) {
      current = detectSectionNumber(line);
      continue;
    }
    if (current) sections[current].push(line);
  }

  return sections;
}

function collectBlocks(lines, matcher) {
  const blocks = [];
  let current = null;

  for (const line of lines) {
    const header = matcher(line);
    if (header) {
      current = { ...header, lines: [] };
      blocks.push(current);
    } else if (current && !/^\s*[-*_]{3,}\s*$/.test(line)) {
      current.lines.push(line); // пропускаем markdown-разделители ---
    }
  }

  return blocks;
}

const explanationHeader = (line) => {
  const match = line.match(/^\s*[-*]\s+\*\*(.+?)\*\*\s*$/);
  return match ? { header: cleanText(match[1]) } : null;
};

const rankingHeader = (line) => {
  const match = line.match(/^\s*\d+\.\s+\*\*(.+?)\*\*\s*(?:\*\((.+?)\)\*)?\s*$/);
  return match
    ? { header: cleanText(match[1]), priority: cleanText(match[2]) }
    : null;
};

const recommendationHeader = (line) => {
  const match = line.match(/^\s*[-*]\s+\*\*(.+?)\*\*\s*(.*)$/);
  return match
    ? { header: cleanText(match[1]), inline: cleanText(match[2]) }
    : null;
};

function extractExplanation(lines) {
  const text = cleanText(lines.join(' '));
  const what = text.match(/Что не так\s*:?\s*(.*?)(?:Почему это важно|$)/i);
  const why = text.match(/Почему это важно\s*:?\s*(.*)$/i);
  const whatText = cleanText(what?.[1]);
  const whyText = cleanText(why?.[1]);

  if (!whatText && !whyText) return { what: text, why: '' };
  return { what: whatText, why: whyText };
}

function extractReason(lines) {
  const text = cleanText(lines.join(' '));
  const match = text.match(/Причина\s*:?\s*(.*)$/i);
  return cleanText(match?.[1] || text);
}

function levelFromPriority(priority, type, index) {
  const text = (priority || '').toLowerCase();

  if (text) {
    if (/крит|важнее всего/.test(text)) return 'critical';
    if (/высок/.test(text)) return 'high';
    if (/средн/.test(text)) return 'medium';
    if (/низк/.test(text)) return 'low';
  }

  if (type === 'BUG' || type === 'VULNERABILITY') {
    return index === 0 ? 'critical' : 'high';
  }
  return 'medium';
}

function normalizeType(value) {
  return (value || '').replace(/[\s_]/g, '').toUpperCase();
}

function parseRecommendationTarget(header) {
  const cleaned = header.replace(/^для\s+/i, '').replace(/:\s*$/, '');
  const match = cleaned.match(/^(.*?)\s+(?:в|in)\s+([^\s:]+):(.*)$/i);
  if (!match) return null;

  return {
    type: normalizeType(match[1]),
    file: match[2].trim(),
    lines: (match[3].match(/\d+/g) || []).map(Number),
  };
}

function matchesTarget(finding, target) {
  if (!target || !finding.file) return false;
  if (target.file.toLowerCase() !== finding.file.toLowerCase()) return false;
  if (target.lines.length && !target.lines.includes(finding.line)) return false;
  if (target.type && normalizeType(finding.type) !== target.type) return false;
  return true;
}

function buildFinding(header, id) {
  const location = parseLocation(header);
  return {
    id,
    title: header,
    type: location?.type || 'ISSUE',
    typeLabel: TYPE_LABELS[location?.type] || 'Проблема',
    file: location?.file || '',
    line: location?.line ?? null,
    what: '',
    why: '',
    reason: '',
    recommendation: '',
    priorityLabel: '',
    level: levelFromPriority('', location?.type, 0),
    rank: null,
  };
}

export function parseGigachatReport(rawText) {
  const text = String(rawText ?? '').replace(/\r\n?/g, '\n');
  const sections = splitSections(text);

  const explanationBlocks = collectBlocks(sections[1], explanationHeader);
  const rankingBlocks = collectBlocks(sections[2], rankingHeader);
  const recommendationBlocks = collectBlocks(sections[3], recommendationHeader);

  const findings = explanationBlocks.map((block, index) => {
    const finding = buildFinding(block.header, `finding-${index + 1}`);
    const body = extractExplanation(block.lines);
    finding.what = body.what;
    finding.why = body.why;
    return finding;
  });

  const findByLocation = (location) =>
    findings.find(
      (item) =>
        item.file.toLowerCase() === location.file.toLowerCase() &&
        item.line === location.line,
    );

  rankingBlocks.forEach((block, index) => {
    const location = parseLocation(block.header);
    const existing = location ? findByLocation(location) : null;
    const finding = existing || buildFinding(block.header, `ranking-${index + 1}`);

    if (!existing) findings.push(finding);

    finding.reason = extractReason(block.lines);
    finding.priorityLabel = block.priority || '';
    finding.level = levelFromPriority(block.priority, finding.type, index);
    finding.rank = index + 1;
  });

  const generalRecommendations = [];
  for (const block of recommendationBlocks) {
    const value = cleanText(block.inline || block.lines.join(' '));
    if (!value) continue;

    const target = parseRecommendationTarget(block.header);
    const matched = findings.filter((finding) => matchesTarget(finding, target));

    if (!matched.length) {
      generalRecommendations.push({
        id: `recommendation-${generalRecommendations.length + 1}`,
        title: block.header,
        text: value,
      });
      continue;
    }

    for (const finding of matched) {
      finding.recommendation = finding.recommendation
        ? `${finding.recommendation} ${value}`
        : value;
    }
  }

  findings.sort((a, b) => {
    if (a.rank && b.rank) return a.rank - b.rank;
    if (a.rank) return -1;
    if (b.rank) return 1;

    const byLevel = LEVELS[a.level].weight - LEVELS[b.level].weight;
    return byLevel !== 0 ? byLevel : a.title.localeCompare(b.title, 'ru');
  });

  const counts = {
    total: findings.length,
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    bugs: 0,
    smells: 0,
  };

  for (const finding of findings) {
    counts[finding.level] += 1;
    if (finding.type === 'BUG') counts.bugs += 1;
    if (finding.type === 'CODE_SMELL') counts.smells += 1;
  }

  return {
    findings,
    generalRecommendations,
    counts,
    raw: text,
    hasStructure: explanationBlocks.length > 0 || rankingBlocks.length > 0,
  };
}

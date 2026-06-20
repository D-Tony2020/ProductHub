// ProductHub 负载测试（k6）。仅在 staging 跑，绝不打 prod。
// 合格线（SLA 务实档）写进 thresholds：p95 检索/详情 <1s、错误率 <0.5%。
// 运行：
//   k6 run -e BASE_URL=https://staging.example.com -e PH_USER=admin -e PH_PASS=*** producthub-loadtest.js
//   阶梯加压默认到 20 并发（项目目标并发≤20）；拐点测试改 STAGE=breakpoint 见底部注释。
import http from 'k6/http';
import { check, sleep, group } from 'k6';

const BASE = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const USER = __ENV.PH_USER || 'admin';
const PASS = __ENV.PH_PASS || '';
const ROOT_TYPE_ID = __ENV.ROOT_TYPE_ID || '26';     // 干粉灭火器（按目标库调整）
const SP_PAIR = __ENV.SP_PAIR || '3:24';             // 结构化检索样例（供应商:件类型）

export const options = {
  scenarios: {
    ramp: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '1m', target: 5 },
        { duration: '2m', target: 20 },   // 升到目标并发 20
        { duration: '3m', target: 20 },   // 稳态 3 分钟
        { duration: '1m', target: 0 },
      ],
      gracefulRampDown: '20s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.005'],                          // 错误率 <0.5%
    'http_req_duration{scn:检索}': ['p(95)<1000', 'p(99)<2000'],
    'http_req_duration{scn:详情}': ['p(95)<1000', 'p(99)<2000'],
    'http_req_duration{scn:结构化}': ['p(95)<1500'],
    'http_req_duration{scn:统计}': ['p(95)<800'],
  },
};

export function setup() {
  const r = http.post(`${BASE}/api/v1/auth/login`,
    JSON.stringify({ username: USER, password: PASS }),
    { headers: { 'Content-Type': 'application/json' } });
  check(r, { '登录 200': (x) => x.status === 200 });
  return { tok: r.json('access_token') };
}

export default function (data) {
  const h = { headers: { Authorization: `Bearer ${data.tok}` } };
  const roll = Math.random();

  if (roll < 0.5) {
    // 50% 货架检索（高频）
    const r = http.get(`${BASE}/api/v1/skus?page=1&page_size=20&sort=recent`,
      Object.assign({ tags: { scn: '检索' } }, h));
    check(r, { '检索 200': (x) => x.status === 200 });
  } else if (roll < 0.75) {
    // 25% 详情（含 BOM，N+1 已优化）
    const list = http.get(`${BASE}/api/v1/skus?page=1&page_size=1`,
      Object.assign({ tags: { scn: '检索' } }, h));
    const id = list.json('items.0.id');
    if (id) {
      const r = http.get(`${BASE}/api/v1/skus/${id}`,
        Object.assign({ tags: { scn: '详情' } }, h));
      check(r, { '详情 200': (x) => x.status === 200 });
    }
  } else if (roll < 0.85) {
    // 10% 统计/全貌
    const r = http.get(`${BASE}/api/v1/skus/stats`,
      Object.assign({ tags: { scn: '统计' } }, h));
    check(r, { '统计 200': (x) => x.status === 200 });
  } else {
    // 15% 结构化检索（多对来源）
    const r = http.get(`${BASE}/api/v1/skus?root_type_id=${ROOT_TYPE_ID}&sp_pair=${SP_PAIR}&page_size=20`,
      Object.assign({ tags: { scn: '结构化' } }, h));
    check(r, { '结构化 200': (x) => x.status === 200 });
  }
  sleep(Math.random() * 1 + 0.5);   // 思考时间 0.5-1.5s
}

// 拐点测试：把上面 scenarios.ramp.stages 末段 target 改为持续上升（如 30/50/80），
//   观察 p95 越过 1s 或 http_req_failed 越过 0.5% 的并发点 = 容量上限，用于验证选型规格是否够用。
// 浸泡测试：单独跑 constant-vus 10 VU × 2-4h，结合服务端内存/连接数监控查泄漏与慢增长。

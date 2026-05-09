// Unit tests for the pure helpers driving the verdict hero.
// Run with: node --test src/lib/*.test.ts (Node 22+ strips TS natively).
//
// No test framework is installed; we use the Node built-in node:test + node:assert.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { livePillars, topStrengths, topRisks, PILLAR_ORDER, type AgentReportLike } from './strengths.ts';

function rep(overrides: Partial<AgentReportLike> & { agent_name?: string } = {}): AgentReportLike {
    return {
        status: 'complete',
        score: 6.5,
        key_findings: [],
        risk_flags: [],
        signal_line: '',
        ...overrides,
    };
}

test('livePillars returns five pillars when all complete', () => {
    const agents: Record<string, AgentReportLike | undefined> = {};
    PILLAR_ORDER.forEach(p => {
        agents[p.node] = rep({ score: 6.0 });
    });
    const pillars = livePillars(agents);
    assert.equal(pillars.length, 5);
});

test('livePillars excludes degraded reports (score=null)', () => {
    const agents = {
        financial_node: rep({ score: 7.0 }),
        risk_node: rep({ score: null, status: 'error', degraded: true }),
        technical_node: rep({ score: 6.0 }),
    };
    const pillars = livePillars(agents);
    assert.equal(pillars.length, 2);
    assert.ok(!pillars.find(p => p.node === 'risk_node'));
});

test('topStrengths only includes pillars >= 6 and is sorted by score desc', () => {
    const agents = {
        financial_node: rep({ score: 8.2, signal_line: 'ROE 18%', agent_name: 'Financial Analyst' }),
        technical_node: rep({ score: 7.6, signal_line: 'Golden cross', agent_name: 'Technical Analyst' }),
        sentiment_node: rep({ score: 5.5, signal_line: 'Mixed', agent_name: 'Sentiment Analyst' }),
        risk_node:      rep({ score: 4.0, agent_name: 'Risk Analyst' }),
    };
    const out = topStrengths(agents, 3);
    assert.equal(out.length, 2);                        // sentiment 5.5 + risk 4.0 dropped
    assert.equal(out[0].pillar, 'Financial');
    assert.equal(out[0].score, 8.2);
    assert.equal(out[0].text, 'ROE 18%');
    assert.equal(out[1].pillar, 'Technical');
});

test('topStrengths respects the limit', () => {
    const agents: Record<string, AgentReportLike | undefined> = {};
    PILLAR_ORDER.forEach((p, i) => {
        agents[p.node] = rep({ score: 7 + i * 0.1, signal_line: `s${i}` });
    });
    const out = topStrengths(agents, 2);
    assert.equal(out.length, 2);
});

test('topStrengths falls back from signal_line to first finding', () => {
    const agents = {
        financial_node: rep({
            score: 7.5,
            signal_line: '',
            key_findings: ['Margins expanding', 'Debt manageable'],
            agent_name: 'Financial Analyst',
        }),
    };
    const out = topStrengths(agents, 3);
    assert.equal(out.length, 1);
    assert.equal(out[0].text, 'Margins expanding');
});

test('topRisks surfaces lowest-scoring pillars first', () => {
    const agents = {
        financial_node: rep({ score: 8.0, agent_name: 'Financial Analyst' }),
        risk_node:      rep({ score: 3.0, signal_line: 'High volatility', agent_name: 'Risk Analyst' }),
        macro_governance_node: rep({ score: 4.5, signal_line: 'Headwinds', agent_name: 'Macro & Governance Analyst' }),
    };
    const out = topRisks(agents, 3);
    assert.equal(out.length, 2);
    assert.equal(out[0].pillar, 'Risk');
    assert.equal(out[0].score, 3.0);
    assert.equal(out[1].pillar, 'Macro & Gov');
});

test('topRisks pulls risk_flags first when present', () => {
    const agents = {
        risk_node: rep({
            score: 3.5,
            signal_line: 'Fallback line',
            risk_flags: ['ATR widening 30% MoM'],
            agent_name: 'Risk Analyst',
        }),
    };
    const out = topRisks(agents, 3);
    assert.equal(out[0].text, 'ATR widening 30% MoM');
});

test('topRisks includes high-scoring pillars that have risk_flags', () => {
    const agents = {
        // Strong overall (8.0) but with flags worth surfacing
        financial_node: rep({
            score: 8.0,
            risk_flags: ['Large goodwill on balance sheet'],
            agent_name: 'Financial Analyst',
        }),
    };
    const out = topRisks(agents, 3);
    assert.equal(out.length, 1);
    assert.equal(out[0].pillar, 'Financial');
});

test('topRisks limit is respected even with mixed sources', () => {
    const agents = {
        financial_node: rep({ score: 4.0 }),
        technical_node: rep({ score: 3.5 }),
        risk_node:      rep({ score: 3.0 }),
        sentiment_node: rep({ score: 4.5 }),
    };
    const out = topRisks(agents, 2);
    assert.equal(out.length, 2);
    assert.equal(out[0].score, 3.0);  // lowest first
});

test('empty agents map returns empty arrays', () => {
    assert.deepEqual(topStrengths({}, 3), []);
    assert.deepEqual(topRisks({}, 3), []);
});

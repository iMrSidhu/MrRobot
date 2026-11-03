import { describe, expect, it } from 'vitest';
import { mapRepoDetail, toSeverity } from './legacy';

const repo = {
  id: 1,
  name: 'owner/repo',
  url: 'https://example.invalid/owner/repo',
  stars: 10,
  status: 'DONE',
  synthesis_path: 's.json',
  security_report_path: 'vault/owner-repo.md',
  security_json_path: 'sec.json',
  error: null,
  timestamp: '2026-11-04T00:00:00.000Z',
};

describe('mapRepoDetail', () => {
  it('keeps claims and reality as separate unpaired lists', () => {
    const result = mapRepoDetail({
      repo,
      synthesis: {
        architecture: 'One service.',
        marketing_claims: ['a', 'b'],
        verified_reality: ['x'],
        gaps: [],
        capability_tags: ['tag'],
      },
      security: null,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.provenance).toBe('legacy_unverified');
    expect(result.value.synthesis.state).toBe('available');
    if (result.value.synthesis.state !== 'available') return;
    expect(result.value.synthesis.value.claims).toEqual(['a', 'b']);
    expect(result.value.synthesis.value.reality).toEqual(['x']);
  });

  it('treats a missing security artifact as missing data, not a clean scan', () => {
    const result = mapRepoDetail({ repo, synthesis: null, security: null });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.security.state).toBe('unavailable');
    if (result.value.security.state !== 'unavailable') return;
    expect(result.value.security.reason).toMatch(/not a clean scan/i);
  });

  it('reports an unreadable artifact as invalid instead of empty', () => {
    const result = mapRepoDetail({ repo, synthesis: 'garbage', security: { findings: {} } });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.synthesis.state).toBe('invalid');
    expect(result.value.security.state).toBe('invalid');
  });

  it('drops unusable findings and counts them', () => {
    const result = mapRepoDetail({
      repo,
      synthesis: null,
      security: {
        findings: [
          { severity: 'high', file: 'a.py', line: 3, description: 'token in source', mitigation: 'rotate' },
          { severity: 'CRITICAL', description: 'no file or line' },
          { severity: 'LOW' },
          'not an object',
        ],
      },
    });

    expect(result.ok).toBe(true);
    if (!result.ok || result.value.security.state !== 'available') return;
    expect(result.value.security.value.findings).toHaveLength(2);
    expect(result.value.security.dropped).toBe(2);
    expect(result.value.security.value.findings[0]?.severity).toBe('HIGH');
    expect(result.value.security.value.findings[1]?.file).toBeNull();
  });

  it('rejects a payload with no usable repo identity', () => {
    expect(mapRepoDetail({ synthesis: null }).ok).toBe(false);
    expect(mapRepoDetail({ repo: { name: 'x' } }).ok).toBe(false);
    expect(mapRepoDetail(null).ok).toBe(false);
  });

  it('never invents a markdown report', () => {
    const result = mapRepoDetail({ repo: { ...repo, security_report_path: null }, synthesis: null, security: null });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.markdownReport).toBe('unavailable');
  });
});

describe('toSeverity', () => {
  it('normalises case and keeps unknown values explicit', () => {
    expect(toSeverity(' critical ')).toBe('CRITICAL');
    expect(toSeverity('Medium')).toBe('MEDIUM');
    expect(toSeverity('SEVERE')).toBe('UNKNOWN');
    expect(toSeverity('')).toBe('UNKNOWN');
  });
});

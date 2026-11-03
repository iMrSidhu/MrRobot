import { describe, expect, it } from 'vitest';
import { REFRESH_EVENT_TYPES, parseSseFrame } from './events';

const frame = (data: unknown, id = '7', type = 'SECURITY_DONE') =>
  `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(data)}`;

const body = {
  repo_id: 900001,
  type: 'SECURITY_DONE',
  message: '15 critical, 15 high',
  payload: { findings: 30 },
  timestamp: '2026-11-04T10:00:00',
};

describe('parseSseFrame', () => {
  it('reads id, type, message and payload', () => {
    expect(parseSseFrame(frame(body))).toEqual({
      id: 7,
      repoId: 900001,
      type: 'SECURITY_DONE',
      message: '15 critical, 15 high',
      payload: { findings: 30 },
      timestamp: '2026-11-04T10:00:00',
    });
  });

  it('drops a frame without a usable id, because replay would loop', () => {
    expect(parseSseFrame(`event: REPORTED\ndata: ${JSON.stringify(body)}`)).toBeNull();
    expect(parseSseFrame(frame(body, 'abc'))).toBeNull();
  });

  it('drops malformed JSON instead of throwing', () => {
    expect(parseSseFrame('id: 3\nevent: ERROR\ndata: {not json')).toBeNull();
    expect(parseSseFrame('id: 3\nevent: ERROR\ndata: [1,2]')).toBeNull();
  });

  it('falls back to the frame event name and an empty payload', () => {
    const parsed = parseSseFrame(`id: 9\nevent: RATE_LIMIT\ndata: ${JSON.stringify({ message: 'slow down' })}`);
    expect(parsed?.type).toBe('RATE_LIMIT');
    expect(parsed?.payload).toEqual({});
    expect(parsed?.repoId).toBeNull();
  });
});

describe('REFRESH_EVENT_TYPES', () => {
  it('refetches on result events but not on progress chatter', () => {
    expect(REFRESH_EVENT_TYPES.has('REPORTED')).toBe(true);
    expect(REFRESH_EVENT_TYPES.has('DISCOVERED')).toBe(false);
    expect(REFRESH_EVENT_TYPES.has('ANALYSIS_START')).toBe(false);
  });
});

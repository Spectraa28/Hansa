// The eight places Hansa's investigation looks. Keys match the categories the backend records in `coverage`.
export const areas = [
  { key: 'Context', name: 'Prompt structure', covers: 'What every call carries: system prompt, history and context that gets sent again and again.' },
  { key: 'Tools', name: 'Tool schemas', covers: 'Tool definitions shipped on every call, and tools the agent never uses.' },
  { key: 'Orchestration', name: 'Agent design', covers: 'How agents are split up and hand off: extra hops, routers that only forward, loops.' },
  { key: 'Model choice', name: 'Model choice', covers: 'A large model doing a job a small one would pass.' },
  { key: 'Memory', name: 'Memory', covers: 'What is carried between turns, and what is carried for nothing.' },
  { key: 'Output', name: 'Output', covers: 'Answers longer or more structured than anything downstream needs.' },
  { key: 'Latency', name: 'Latency', covers: 'Waiting: calls made one after another that could overlap, slow steps on the hot path.' },
  { key: 'Wasted work', name: 'Wasted calls', covers: 'Calls whose result is never used.' },
] as const

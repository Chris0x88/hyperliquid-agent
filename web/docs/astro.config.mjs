import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  integrations: [
    starlight({
      title: 'HyperLiquid Bot Docs',
      description: 'An AI trading co-pilot for HyperLiquid — your keys, your rules.',
      sidebar: [
        { label: 'Getting Started', autogenerate: { directory: 'getting-started' } },
        { label: 'Architecture', autogenerate: { directory: 'architecture' } },
      ],
    }),
  ],
  server: { port: 4321 },
});

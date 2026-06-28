import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { crx } from '@crxjs/vite-plugin';
import manifest from './manifest.json';

export default defineConfig({
  plugins: [
    react(),
    crx({ manifest }),
  ],
  // Content scripts use shadow DOM for style isolation — inline CSS import needed
  build: {
    rollupOptions: {
      input: {
        popup: 'popup.html',
      },
    },
  },
});

import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],build:{outDir:'../nuvora/static',emptyOutDir:true},server:{proxy:{'/api':'http://127.0.0.1:8789','/v1':'http://127.0.0.1:8789'}}});

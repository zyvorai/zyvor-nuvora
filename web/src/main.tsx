// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';
import './styles/apple-story.css';
import './styles/nuvora.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);

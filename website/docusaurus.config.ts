import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'Nuvora',
  tagline: 'Your models. Your knowledge. Your control.',
  favicon: 'img/favicon.svg',

  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  url: 'https://zyvorai.github.io',
  baseUrl: '/zyvor-nuvora/',

  organizationName: 'zyvorai',
  projectName: 'zyvor-nuvora',

  onBrokenLinks: 'throw',

  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  // Screenshots and social art are served from the repo's docs/ folders, so the
  // README and this site share one physical copy of each image.
  staticDirectories: ['static', '../docs/ux', '../docs/social'],

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/zyvorai/zyvor-nuvora/tree/main/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'nuvora-share-card.png',
    colorMode: {
      defaultMode: 'light',
      respectPrefersColorScheme: false,
    },
    navbar: {
      title: 'Nuvora',
      logo: {
        alt: 'Zyvor',
        src: 'img/favicon.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          to: '/gallery',
          label: 'Tour',
          position: 'left',
        },
        {
          href: 'https://github.com/zyvorai/zyvor-nuvora',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {label: 'Quickstart', to: '/docs/getting-started/quickstart'},
            {label: 'Deploy to k3s', to: '/docs/getting-started/deploy'},
            {label: 'Architecture', to: '/docs/core-concepts/architecture'},
            {label: 'Security', to: '/docs/security'},
          ],
        },
        {
          title: 'Project',
          items: [
            {label: 'GitHub', href: 'https://github.com/zyvorai/zyvor-nuvora'},
            {
              label: 'Changelog',
              href: 'https://github.com/zyvorai/zyvor-nuvora/blob/main/CHANGELOG.md',
            },
            {
              label: 'License',
              href: 'https://github.com/zyvorai/zyvor-nuvora/blob/main/LICENSE',
            },
          ],
        },
        {
          title: 'Zyvor',
          items: [
            {label: 'zyvor.dev', href: 'https://zyvor.dev'},
            {label: 'Netra', href: 'https://zyvorai.github.io/zyvor-netra/'},
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Zyvor AI Labs. Apache-2.0.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;

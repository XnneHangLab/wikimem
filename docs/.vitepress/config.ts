import { defineConfig } from "vitepress";

// Deployed as a GitHub Pages project site: https://xnnehanglab.github.io/wikimem/
// If a custom domain is added later, change `base` to "/" and set the CNAME in
// .github/workflows/docs-deploy.yml.
export default defineConfig({
  title: "wikimem",
  base: "/wikimem/",
  lastUpdated: true,

  head: [["link", { rel: "icon", type: "image/svg+xml", href: "/wikimem/logo.svg" }]],

  locales: {
    root: {
      label: "English",
      lang: "en-US",
      description:
        "File-first memory for AI agents: categories + wiki-links over plain markdown.",
      themeConfig: {
        nav: [
          { text: "Guide", link: "/guide/what-is-wikimem" },
          { text: "Reference", link: "/reference/api" },
        ],
        sidebar: {
          "/guide/": [
            {
              text: "Introduction",
              items: [
                { text: "What is wikimem?", link: "/guide/what-is-wikimem" },
                { text: "Getting Started", link: "/guide/getting-started" },
              ],
            },
            {
              text: "Core Concepts",
              items: [
                { text: "Wiki-links", link: "/guide/wiki-links" },
                { text: "Retrieval", link: "/guide/retrieval" },
                { text: "Embedding Fusion", link: "/guide/embedding-fusion" },
              ],
            },
            {
              text: "In Practice",
              items: [
                { text: "Host Integration", link: "/guide/host-integration" },
              ],
            },
          ],
          "/reference/": [
            {
              text: "Reference",
              items: [
                { text: "Core API", link: "/reference/api" },
                { text: "Vectors API", link: "/reference/vectors" },
                { text: "On-disk Format", link: "/reference/file-format" },
              ],
            },
          ],
        },
        editLink: {
          pattern: "https://github.com/XnneHangLab/wikimem/edit/main/docs/:path",
          text: "Edit this page on GitHub",
        },
        footer: {
          message: "Released under the Apache-2.0 License.",
          copyright: "© 2026 XnneHangLab",
        },
      },
    },

    zh: {
      label: "简体中文",
      lang: "zh-CN",
      description: "面向 AI Agent 的文件优先记忆系统：纯 markdown 之上的 categories + wiki-links。",
      themeConfig: {
        nav: [
          { text: "指南", link: "/zh/guide/what-is-wikimem" },
          { text: "参考", link: "/zh/reference/api" },
        ],
        sidebar: {
          "/zh/guide/": [
            {
              text: "介绍",
              items: [
                { text: "什么是 wikimem？", link: "/zh/guide/what-is-wikimem" },
                { text: "快速上手", link: "/zh/guide/getting-started" },
              ],
            },
            {
              text: "核心概念",
              items: [
                { text: "Wiki-links", link: "/zh/guide/wiki-links" },
                { text: "检索", link: "/zh/guide/retrieval" },
                { text: "Embedding 融合", link: "/zh/guide/embedding-fusion" },
              ],
            },
            {
              text: "实践",
              items: [
                { text: "宿主集成", link: "/zh/guide/host-integration" },
              ],
            },
          ],
          "/zh/reference/": [
            {
              text: "参考",
              items: [
                { text: "核心 API", link: "/zh/reference/api" },
                { text: "向量 API", link: "/zh/reference/vectors" },
                { text: "磁盘格式", link: "/zh/reference/file-format" },
              ],
            },
          ],
        },
        editLink: {
          pattern: "https://github.com/XnneHangLab/wikimem/edit/main/docs/:path",
          text: "在 GitHub 上编辑此页",
        },
        outline: { level: "deep", label: "页面导航" },
        lastUpdatedText: "最后更新于",
        docFooter: { prev: "上一页", next: "下一页" },
        darkModeSwitchLabel: "主题",
        sidebarMenuLabel: "菜单",
        returnToTopLabel: "回到顶部",
        langMenuLabel: "切换语言",
        footer: {
          message: "基于 Apache-2.0 许可发布",
          copyright: "© 2026 XnneHangLab",
        },
      },
    },
  },

  themeConfig: {
    logo: "/logo.svg",
    outline: "deep",

    socialLinks: [{ icon: "github", link: "https://github.com/XnneHangLab/wikimem" }],

    search: {
      provider: "local",
      options: {
        locales: {
          zh: {
            translations: {
              button: { buttonText: "搜索文档", buttonAriaLabel: "搜索文档" },
              modal: {
                noResultsText: "无法找到相关结果",
                resetButtonTitle: "清除查询条件",
                footer: { selectText: "选择", navigateText: "切换", closeText: "关闭" },
              },
            },
          },
        },
      },
    },
  },
});

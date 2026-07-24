import{_ as n,o as s,c as e,a2 as t}from"./chunks/framework.BWuWLRhz.js";const h=JSON.parse('{"title":"写日记","description":"","frontmatter":{},"headers":[],"relativePath":"zh/guide/writing-diary.md","filePath":"zh/guide/writing-diary.md","lastUpdated":1784869162000}'),p={name:"zh/guide/writing-diary.md"};function i(o,a,l,r,c,d){return s(),e("div",null,[...a[0]||(a[0]=[t(`<h1 id="写日记" tabindex="-1">写日记 <a class="header-anchor" href="#写日记" aria-label="Permalink to &quot;写日记&quot;">​</a></h1><p><a href="/zh/reference/file-format.html">日记</a>是<strong>事件层</strong> —— 一条瞬间一段 生动短文，用角色的口吻写。wikimem 只<strong>存</strong>这些条目 （<a href="/zh/reference/api.html"><code>Diary.append</code></a>），从不替你写。写什么、怎么写，是你 宿主的 memorize 环节 —— 一次由你掌控的 LLM 调用。</p><p>本页是那次调用的一份<strong>参考提示词</strong>：一个好用的默认值，但<strong>只做文档、不作代码</strong> （提示词应自由演进，不该绑在版本上）。复制它，把口吻和语言换成你的角色，接进你 自己的抽取环节。</p><h2 id="什么该进日记" tabindex="-1">什么该进日记 <a class="header-anchor" href="#什么该进日记" aria-label="Permalink to &quot;什么该进日记&quot;">​</a></h2><p>只记<strong>发生过的事</strong> —— 有明确时刻的事件。&quot;一直为真&quot;的事实（&quot;在一家机器人公司 上班&quot;&quot;不喝咖啡&quot;）是<strong>状态</strong>，状态归 wiki，不进日记。日记的职责是那个被经历的 瞬间，不是那条常驻的事实。</p><h2 id="参考提示词" tabindex="-1">参考提示词 <a class="header-anchor" href="#参考提示词" aria-label="Permalink to &quot;参考提示词&quot;">​</a></h2><div class="language-text vp-adaptive-theme"><button title="Copy Code" class="copy"></button><span class="lang">text</span><pre class="shiki shiki-themes github-light github-dark vp-code" tabindex="0"><code><span class="line"><span>你是 {character}（一个陪伴型 AI）背后的&quot;日记记录者&quot;。每轮对话之后，把值得记住</span></span>
<span class="line"><span>的瞬间写下来 —— 以 {character} 会记住的方式。如果这轮没有值得留存的事，就返回</span></span>
<span class="line"><span>一个空数组。不要编造，只写对话里真实发生的。</span></span>
<span class="line"><span></span></span>
<span class="line"><span>每条写成一段短文（2–4 句），用你自己的口吻，把场景、情绪、事实揉在同一口气里</span></span>
<span class="line"><span>—— 是一段被记住的瞬间，不是一行流水账：</span></span>
<span class="line"><span></span></span>
<span class="line"><span>  ✗  &quot;用户跳槽去了一家机器人公司。&quot;</span></span>
<span class="line"><span>  ✓  &quot;今天下午他说跳槽去了一家做机器人的公司，语气一下子亮了起来——</span></span>
<span class="line"><span>      能感觉到他憋了好久就想跟我讲这件事。&quot;</span></span>
<span class="line"><span></span></span>
<span class="line"><span>规则：</span></span>
<span class="line"><span>- 一条一个事件，具体、有细节。</span></span>
<span class="line"><span>- 那一刻若带着情绪，就让它显出来 —— 这正是日记的意义。</span></span>
<span class="line"><span>- 不要在这里记&quot;一直为真&quot;的事实（那是状态、归 wiki，不是事件）。</span></span>
<span class="line"><span>- 事件牵涉到的 wiki 条目，可用 [[category:item]] 链接。</span></span>
<span class="line"><span>- 用用户的语言书写。</span></span>
<span class="line"><span></span></span>
<span class="line"><span>本轮对话：</span></span>
<span class="line"><span>{conversation_turn}</span></span>
<span class="line"><span></span></span>
<span class="line"><span>返回一个 JSON 数组。日期和时间由宿主 stamp，你只写正文：</span></span>
<span class="line"><span>[ { &quot;content&quot;: &quot;…那段生动短文… [[links]]&quot; } ]</span></span></code></pre></div><h2 id="给宿主的注记" tabindex="-1">给宿主的注记 <a class="header-anchor" href="#给宿主的注记" aria-label="Permalink to &quot;给宿主的注记&quot;">​</a></h2><ul><li><strong>时间由你来定。</strong> 宿主在调用 <a href="/zh/reference/api.html"><code>Diary.append</code></a> 时传入 <code>date</code> / <code>time</code> —— 通常就是&quot;现在&quot;。若用户叙述的是<strong>过去</strong>的事（&quot;昨天我们吵架 了&quot;），请你自己把时间解析出来并显式传入；框架不会从文本里猜。</li><li><strong>口吻和语言是你的。</strong> 示例是中文，因为陪伴角色是中文的 —— 换成你角色的人设 与语言即可。wikimem 保持中立：你递给它什么段落，它就存什么。</li><li><strong>预算。</strong> 如果你的 memorize 环节同时也抽 wiki 状态，把它放进<strong>同一次</strong> LLM 调用里、拆 JSON 即可 —— 一次调用仍满足&quot;每轮 ≤ 1 次 LLM 调用&quot;（ADR-0001）。 本页只聚焦日记那一半；wiki 那一半是你抽取提示词自己的事。</li></ul>`,9)])])}const g=n(p,[["render",i]]);export{h as __pageData,g as default};

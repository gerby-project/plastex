// One MathJax instance for the entire build. stdout is a JSON-lines protocol.
const readline = require('node:readline');
const path = require('node:path');
const {init} = require('mathjax');
console.log = console.warn = (...args) => console.error(...args);

async function main() {
  const config = JSON.parse(process.argv[2] || '{}');
  const load = ['input/tex-base', 'output/svg', '[tex]/ams', '[tex]/newcommand',
    '[tex]/configmacros', '[tex]/boldsymbol', '[tex]/mathtools', '[tex]/begingroup', '[tex]/html'];
  if (config.xypic) load.push('[gerby]/xyjaxv4.js');
  const mj = await init({
    loader: {load, paths: {gerby: path.join(__dirname, 'vendor')},
      dependencies: {'[gerby]/xyjaxv4.js': ['input/tex-base', 'output/svg']}},
    tex: {
      packages: ['base', 'ams', 'newcommand', 'configmacros', 'boldsymbol',
        'mathtools', 'begingroup', 'html', ...(config.xypic ? ['xypic'] : [])],
      // LaTeX's empty replacement macro is used to separate leading '['
      // cell text from Xy-pic's optional arguments (including in Kerodon).
      macros: {empty: '', ...(config.macros || {})}, tags: 'none',
      formatError: (_jax, error) => { throw error; }
    },
    svg: {fontCache: 'none', font: 'mathjax-tex', linebreaks: {inline: false}},
    options: {
      compileError: (_document, _math, error) => { throw error; },
      typesetError: (_document, _math, error) => { throw error; }
    },
    startup: {typeset: false}
  });
  const adaptor = mj.startup.adaptor;
  process.stdout.write(JSON.stringify({ready: true, version: mj.version}) + '\n');
  for await (const line of readline.createInterface({input: process.stdin})) {
    try {
      const request = JSON.parse(line);
      // Reset equation state; XyJax resets its repositories in its preprocessor.
      mj.texReset();
      const source = '\\begingroupSandbox ' + request.tex;
      if (request.output === 'mathml') {
        const mml = await mj.tex2mmlPromise(source, {display: request.display});
        if (/<merror\b/.test(mml)) throw new Error('MathJax returned an error node');
        process.stdout.write(JSON.stringify({mathml: mml}) + '\n');
        continue;
      }
      const node = await mj.tex2svgPromise(source,
        {display: request.display});
      const svg = adaptor.firstChild(node);
      const mml = mj.startup.toMML(mj.startup.document.outputJax.math.root);
      if (/<merror\b/.test(mml)) throw new Error('MathJax returned an error node');
      process.stdout.write(JSON.stringify({
        // LiteAdaptor serializes HTML, where '<' is legal in attributes; SVG
        // assets are XML documents and must escape it (e.g. @{<->} arrows).
        svg: adaptor.outerHTML(svg).replace(/="([^"]*)"/g,
          (_match, value) => '="' + value.replace(/</g, '&lt;') + '"'), mathml: mml,
        style: adaptor.getAttribute(svg, 'style') || '',
        width: adaptor.getAttribute(svg, 'width'), height: adaptor.getAttribute(svg, 'height')
      }) + '\n');
    } catch (error) {
      process.stdout.write(JSON.stringify({error: error.message || String(error)}) + '\n');
    }
  }
}
main().catch(error => { console.error(error); process.exit(1); });

/** Small DOM helpers. Text is always set via `textContent`, never `innerHTML`. */

export const $ = (id) => document.getElementById(id);

/**
 * Create an element.
 * @param {string} tag
 * @param {Record<string, unknown>} [props]  `class`, `text`, `dataset`, or any DOM property
 * @param {...(Node|string)} children
 */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else node[key] = value;
  }
  node.append(...children);
  return node;
}

export const show = (node) => node.classList.remove('hidden');
export const hide = (node) => node.classList.add('hidden');

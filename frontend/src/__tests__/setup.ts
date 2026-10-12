/**
 * Recent Node versions define a global `localStorage` that is undefined
 * unless started with --localstorage-file, and it shadows jsdom's. Install a
 * plain in-memory Storage so the code under test sees a working one.
 */

class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  get length() { return this.data.size; }
  clear() { this.data.clear(); }
  getItem(key: string) { return this.data.has(key) ? this.data.get(key)! : null; }
  key(index: number) { return [...this.data.keys()][index] ?? null; }
  removeItem(key: string) { this.data.delete(key); }
  setItem(key: string, value: string) { this.data.set(key, String(value)); }
}

const storage = new MemoryStorage();
Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true });
Object.defineProperty(window, 'localStorage', { value: storage, configurable: true });

/** jsdom has no canvas; axe-core probes it for icon ligatures. Report "unsupported" quietly. */
Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', { value: () => null, configurable: true });

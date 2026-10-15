// ES2019+ built-ins Qt's QJSEngine (an ES2017 engine) lacks, used by the
// bundled Genshin Optimizer formula engine.
var globalThis = this;
var process = { env: { NODE_ENV: "production" } };
(function () {
  function def(obj, name, fn) {
    if (!obj[name]) Object.defineProperty(obj, name, { value: fn, writable: true, configurable: true });
  }
  def(Array.prototype, "flat", function (depth) {
    depth = depth === undefined ? 1 : Math.floor(depth);
    var out = [];
    (function walk(arr, d) {
      for (var i = 0; i < arr.length; i++) {
        if (!(i in arr)) continue;
        var v = arr[i];
        if (Array.isArray(v) && d > 0) walk(v, d - 1); else out.push(v);
      }
    })(this, depth);
    return out;
  });
  def(Array.prototype, "flatMap", function (fn, thisArg) {
    return Array.prototype.map.call(this, fn, thisArg).flat(1);
  });
  def(Array.prototype, "at", function (i) {
    i = Math.trunc(i) || 0; if (i < 0) i += this.length;
    return i < 0 || i >= this.length ? undefined : this[i];
  });
  def(Array.prototype, "findLast", function (fn, thisArg) {
    for (var i = this.length - 1; i >= 0; i--) if (fn.call(thisArg, this[i], i, this)) return this[i];
    return undefined;
  });
  def(Array.prototype, "findLastIndex", function (fn, thisArg) {
    for (var i = this.length - 1; i >= 0; i--) if (fn.call(thisArg, this[i], i, this)) return i;
    return -1;
  });
  def(Array.prototype, "toSorted", function (cmp) { return this.slice().sort(cmp); });
  def(Array.prototype, "toReversed", function () { return this.slice().reverse(); });
  def(Object, "fromEntries", function (entries) {
    var o = {};
    var arr = Array.from(entries);
    for (var i = 0; i < arr.length; i++) o[arr[i][0]] = arr[i][1];
    return o;
  });
  def(Object, "hasOwn", function (o, k) { return Object.prototype.hasOwnProperty.call(o, k); });
  def(String.prototype, "trimStart", function () { return this.replace(/^\s+/, ""); });
  def(String.prototype, "trimEnd", function () { return this.replace(/\s+$/, ""); });
  def(String.prototype, "replaceAll", function (a, b) {
    if (a instanceof RegExp) return this.replace(a, b);
    return this.split(a).join(typeof b === "function" ? b(a) : b);
  });
  def(String.prototype, "at", function (i) {
    i = Math.trunc(i) || 0; if (i < 0) i += this.length;
    return i < 0 || i >= this.length ? undefined : this.charAt(i);
  });
})();
// QJSEngine ignores a Proxy's ownKeys trap in Object.keys/entries/values
// (it lists the target's own keys instead), while Reflect.ownKeys honours
// it; the engine relies on those traps. Rebuild the three on Reflect.ownKeys
// with the standard enumerability rule, which is equivalent for every object.
(function () {
  var gopd = Object.getOwnPropertyDescriptor;
  function enumKeys(o) {
    o = Object(o);
    var all = Reflect.ownKeys(o), out = [];
    for (var i = 0; i < all.length; i++) {
      var k = all[i];
      if (typeof k !== "string") continue;
      var d = gopd(o, k);
      if (d && d.enumerable) out.push(k);
    }
    return out;
  }
  Object.keys = enumKeys;
  Object.entries = function (o) { return enumKeys(o).map(function (k) { return [k, o[k]]; }); };
  Object.values = function (o) { return enumKeys(o).map(function (k) { return o[k]; }); };
})();
// QJSEngine's WeakMap can crash (a segfault in WeakMap.has, seen while the
// optimizer detaches and prunes formulas). The engine only uses weak
// collections as caches, so ordinary Map/Set are a safe stand-in: entries are
// kept for the engine's lifetime instead of being collected.
WeakMap = function WeakMap(entries) { return new Map(entries); };
WeakSet = function WeakSet(values) { return new Set(values); };
// zod references BigInt at load time; QJSEngine has none.
if (typeof globalThis.BigInt === 'undefined') { globalThis.BigInt = function (v) { return Number(v) }; globalThis.BigInt.asIntN = function (b, v) { return v }; globalThis.BigInt.asUintN = function (b, v) { return v } }

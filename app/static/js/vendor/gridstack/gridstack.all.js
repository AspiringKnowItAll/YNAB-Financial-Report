/**
 * gridstack.js — STUB for development
 *
 * Copyright (c) 2021-present Alain Dumesny, Dylan Weiss, Lyor Goldstein
 * MIT License — https://github.com/gridstack/gridstack.js/blob/master/LICENSE
 *
 * This is a minimal API-surface stub. The real gridstack.js v10.x library
 * should be vendored here for production use. All methods are safe no-ops
 * that return empty arrays/objects so dependent code runs without errors.
 */

(function (root) {
  'use strict';

  /**
   * @constructor
   * @param {HTMLElement} el - The grid container element.
   * @param {Object} opts - Configuration options.
   */
  function GridStackInstance(el, opts) {
    this.el = el;
    this.opts = opts || {};
    this._listeners = {};
  }

  GridStackInstance.prototype.on = function (event, callback) {
    if (!this._listeners[event]) {
      this._listeners[event] = [];
    }
    this._listeners[event].push(callback);
    return this;
  };

  GridStackInstance.prototype.off = function (event) {
    if (event) {
      delete this._listeners[event];
    } else {
      this._listeners = {};
    }
    return this;
  };

  GridStackInstance.prototype._emit = function (event) {
    var args = Array.prototype.slice.call(arguments, 1);
    var listeners = this._listeners[event] || [];
    for (var i = 0; i < listeners.length; i++) {
      listeners[i].apply(this, args);
    }
  };

  GridStackInstance.prototype.makeWidget = function (el) {
    return el || null;
  };

  GridStackInstance.prototype.removeWidget = function (el, removeDom) {
    if (removeDom !== false && el && el.parentNode) {
      el.parentNode.removeChild(el);
    }
    return this;
  };

  GridStackInstance.prototype.removeAll = function () {
    return this;
  };

  GridStackInstance.prototype.compact = function () {
    return this;
  };

  GridStackInstance.prototype.save = function () {
    return [];
  };

  GridStackInstance.prototype.load = function () {
    return this;
  };

  GridStackInstance.prototype.addWidget = function (el) {
    if (typeof el === 'object' && !(el instanceof HTMLElement)) {
      // Options object passed — create element stub
      var node = document.createElement('div');
      node.className = 'grid-stack-item';
      if (this.el) {
        this.el.appendChild(node);
      }
      return node;
    }
    return el || null;
  };

  GridStackInstance.prototype.update = function () {
    return this;
  };

  GridStackInstance.prototype.column = function (val) {
    if (val !== undefined) {
      this.opts.column = val;
      return this;
    }
    return this.opts.column || 12;
  };

  GridStackInstance.prototype.getGridItems = function () {
    if (!this.el) return [];
    return Array.prototype.slice.call(
      this.el.querySelectorAll('.grid-stack-item')
    );
  };

  GridStackInstance.prototype.batchUpdate = function () {
    return this;
  };

  GridStackInstance.prototype.commit = function () {
    return this;
  };

  GridStackInstance.prototype.destroy = function () {
    this._listeners = {};
    return this;
  };

  GridStackInstance.prototype.disable = function () {
    return this;
  };

  GridStackInstance.prototype.enable = function () {
    return this;
  };

  GridStackInstance.prototype.movable = function () {
    return this;
  };

  GridStackInstance.prototype.resizable = function () {
    return this;
  };

  /** Static factory */
  var GridStack = {
    init: function (opts, elOrSelector) {
      var el;
      if (typeof elOrSelector === 'string') {
        el = document.querySelector(elOrSelector);
      } else if (elOrSelector instanceof HTMLElement) {
        el = elOrSelector;
      } else {
        el = document.querySelector('.grid-stack');
      }
      return new GridStackInstance(el, opts);
    },
  };

  /** Minimal engine stub */
  var GridStackEngine = function () {};
  GridStackEngine.prototype.compact = function () { return this; };

  // Export
  root.GridStack = GridStack;
  root.GridStackEngine = GridStackEngine;

})(typeof window !== 'undefined' ? window : this);

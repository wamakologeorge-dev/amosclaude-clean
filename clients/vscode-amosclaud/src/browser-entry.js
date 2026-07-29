'use strict';

const baseExtension = require('../web-extension');
const { registerTerminal } = require('./terminal');

function activate(context) {
  baseExtension.activate(context);
  registerTerminal(context);
}

module.exports = {
  ...baseExtension,
  activate,
};

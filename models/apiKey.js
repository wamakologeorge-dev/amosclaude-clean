// models/apiKey.js
const mongoose = require('mongoose');

const apiKeySchema = new mongoose.Schema({
  key: String,
  hashedKey: String,
  expiresAt: Date,
  client: String,
});

const ApiKey = mongoose.model('ApiKey', apiKeySchema);

module.exports = ApiKey;

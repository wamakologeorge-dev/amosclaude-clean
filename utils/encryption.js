// utils/encryption.js
const crypto = require('crypto');
const bcrypt = require('bcrypt');

const encryptApiKey = (apiKey) => {
  const salt = bcrypt.genSaltSync(10);
  const hashedApiKey = bcrypt.hashSync(apiKey, salt);
  return hashedApiKey;
};

const decryptApiKey = (hashedApiKey) => {
  return bcrypt.compareSync(hashedApiKey, 'your-plaintext-api-key');
};

module.exports = { encryptApiKey, decryptApiKey };

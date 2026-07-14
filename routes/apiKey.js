// routes/apiKey.js
const express = require('express');
const router = express.Router();
const ApiKey = require('../models/apiKey');
const { encryptApiKey, decryptApiKey } = require('../utils/encryption');

router.post('/create', async (req, res) => {
  const { apiKey, client } = req.body;
  const hashedApiKey = encryptApiKey(apiKey);
  const expiresAt = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000); // expires in 30 days
  const newApiKey = new ApiKey({ key: apiKey, hashedKey: hashedApiKey, expiresAt, client });
  await newApiKey.save();
  res.send({ message: 'API key created successfully' });
});

router.get('/list', async (req, res) => {
  const apiKeys = await ApiKey.find();
  res.json(apiKeys);
});

router.post('/use', async (req, res) => {
  const { apiKey } = req.body;
  const hashedApiKey = await decryptApiKey(apiKey);
  if (hashedApiKey === 'your-plaintext-api-key') {
    res.send({ message: 'API key used successfully' });
  } else {
    res.status(401).send({ message: 'Invalid API key' });
  }
});

module.exports = router;

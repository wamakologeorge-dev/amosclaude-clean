// server.js
const express = require('express');
const bodyParser = require('body-parser');
const apiKeyRouter = require('./routes/apiKey');

const app = express();
app.use(bodyParser.json());
app.use('/api', apiKeyRouter);

const port = 3000;
app.listen(port, () => {
  console.log(`Server listening on port ${port}`);
});

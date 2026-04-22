const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');
const path = require('path');
const { v4: uuidv4 } = require('uuid');
const { recordPayment } = require('./utils/googleSheets');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;

app.set('view engine', 'ejs');
app.use(express.static('public'));
app.use(bodyParser.json());

// Routes
app.get('/', (req, res) => {
    // Generate a new orderId for each session
    const orderId = uuidv4();
    const clientKey = process.env.TOSS_CLIENT_KEY || 'test_ck_D5GePWvyJnrK0W0k6q8gLzN97Ejq';
    res.render('index', { clientKey, orderId });
});

app.get('/success', async (req, res) => {
    const { paymentKey, orderId, amount } = req.query;
    
    try {
        console.log(`Confirming payment: orderId=${orderId}, amount=${amount}`);

        // confirm payment with Toss API
        // Secret Key needs to be base64 encoded with a colon appended
        const secretKey = process.env.TOSS_SECRET_KEY || 'test_sk_zRKBSZywO4DAj07Plq283yGr5WoG';
        const encryptedSecretKey = Buffer.from(secretKey + ':').toString('base64');

        const response = await axios.post('https://api.tosspayments.com/v1/payments/confirm', {
            paymentKey,
            orderId,
            amount
        }, {
            headers: {
                Authorization: `Basic ${encryptedSecretKey}`,
                'Content-Type': 'application/json'
            }
        });

        const paymentData = response.data;
        console.log('Payment confirmed:', paymentData.orderName);

        // Record to Google Sheets
        // Note: For real recording, user must provide GOOGLE_SHEET_ID and service-account.json
        await recordPayment({
            orderId: paymentData.orderId,
            amount: paymentData.totalAmount,
            orderName: paymentData.orderName,
            approvedAt: paymentData.approvedAt,
            method: paymentData.method
        });

        res.render('success', { orderId, orderName: paymentData.orderName });
    } catch (error) {
        console.error('Payment Confirm Error:', error.response ? error.response.data : error.message);
        const errorMessage = error.response ? error.response.data.message : 'Payment Confirmation Failed';
        const errorCode = error.response ? error.response.data.code : 'UNKNOWN_ERROR';
        res.render('fail', { message: errorMessage, code: errorCode });
    }
});

app.get('/fail', (req, res) => {
    const { message, code } = req.query;
    res.render('fail', { message, code });
});

// Download route (optional, can be static too)
app.get('/download-guide', (req, res) => {
    const file = path.join(__dirname, 'public', 'guide.pdf');
    res.download(file, 'Incheon_Chamber_Training_Guide.pdf', (err) => {
        if (err) {
            console.error('File download error:', err);
            res.status(500).send('Error downloading file.');
        }
    });
});

app.listen(PORT, () => console.log(`Server running on http://localhost:${PORT}`));

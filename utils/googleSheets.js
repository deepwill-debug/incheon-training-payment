const { google } = require('googleapis');
const path = require('path');
require('dotenv').config();

async function recordPayment(paymentData) {
    try {
        if (!process.env.GOOGLE_SHEET_ID) {
            console.log('No GOOGLE_SHEET_ID in environment. Skipping Google Sheet recording.');
            console.log('Data to be recorded:', paymentData);
            return;
        }

        // Try to load auth from environment variable content first, then file
        // If GOOGLE_SERVICE_ACCOUNT_JSON is set (raw json string), use that
        // Otherwise look for file path

        let auth;
        if (process.env.GOOGLE_SERVICE_ACCOUNT_JSON) {
            const credentials = JSON.parse(process.env.GOOGLE_SERVICE_ACCOUNT_JSON);
            auth = new google.auth.GoogleAuth({
                credentials,
                scopes: ['https://www.googleapis.com/auth/spreadsheets'],
            });
        } else {
            const keyFile = process.env.GOOGLE_SERVICE_ACCOUNT_KEY_PATH || path.join(__dirname, '../service-account.json');
            auth = new google.auth.GoogleAuth({
                keyFile,
                scopes: ['https://www.googleapis.com/auth/spreadsheets'],
            });
        }

        const sheets = google.sheets({ version: 'v4', auth });

        // Prepare row data
        // Order: Date, Course Name, Method, Amount, Order ID
        const values = [[
            new Date(paymentData.approvedAt).toLocaleString('ko-KR'),
            paymentData.orderName,
            paymentData.method,
            paymentData.amount,
            paymentData.orderId
        ]];

        const response = await sheets.spreadsheets.values.append({
            spreadsheetId: process.env.GOOGLE_SHEET_ID,
            range: '2026_교육신청현황!A:E',
            valueInputOption: 'USER_ENTERED',
            resource: {
                values
            }
        });

        console.log('Successfully recorded to Google Sheet:', response.data.updates.updatedRange);
    } catch (error) {
        console.error('Failed to record to Google Sheet:', error.message);
        // Start verify mock logic if needed or just log
    }
}

module.exports = { recordPayment };

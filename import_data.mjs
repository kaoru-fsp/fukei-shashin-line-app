import { initializeApp } from "firebase/app";
import { getFirestore, collection, doc, writeBatch } from "firebase/firestore";
import Papa from "papaparse";
import fs from "fs";

const firebaseConfig = {
  apiKey: "AIzaSyAn4I5XBMPzggAXM0FsTZH9Ilxx96mZQe8",
  authDomain: "gen-lang-client-0328956131.firebaseapp.com",
  projectId: "gen-lang-client-0328956131",
  storageBucket: "gen-lang-client-0328956131.firebasestorage.app",
  messagingSenderId: "529174988876",
  appId: "1:529174988876:web:82e6d0595ce23fd19e4ce9"
};

const app = initializeApp(firebaseConfig);
const db = getFirestore(app, "(default)");

async function importData() {
  console.log("Reading CSV...");
  const csvText = fs.readFileSync("./public/sample_database.csv", "utf-8");
  
  Papa.parse(csvText, {
    header: true,
    skipEmptyLines: true,
    complete: async (results) => {
      const data = results.data;
      console.log(`Found ${data.length} records. Uploading...`);
      
      const BATCH_SIZE = 400;
      let currentBatch = writeBatch(db);
      let operationCount = 0;
      let batchesCommitted = 0;
      
      try {
        for (let i = 0; i < data.length; i++) {
          const row = data[i];
          const docRef = doc(collection(db, "contests"));
          currentBatch.set(docRef, row);
          
          operationCount++;
          
          if (operationCount >= BATCH_SIZE || i === data.length - 1) {
            await currentBatch.commit();
            batchesCommitted++;
            console.log(`Committed batch ${batchesCommitted}`);
            currentBatch = writeBatch(db);
            operationCount = 0;
          }
        }
        console.log("Import completed successfully!");
        process.exit(0);
      } catch (err) {
        console.error("Error writing to Firestore:", err);
        process.exit(1);
      }
    },
    error: (err) => {
      console.error("Error parsing CSV:", err);
      process.exit(1);
    }
  });
}

importData();

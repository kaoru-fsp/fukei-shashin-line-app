import { initializeApp } from "firebase/app";
import { getFirestore, collection, getDocs, writeBatch, doc } from "firebase/firestore";
import fs from "fs";
import Papa from "papaparse";

const firebaseConfig = JSON.parse(fs.readFileSync("./src/firebase-applet-config.json", "utf8"));
const app = initializeApp(firebaseConfig);
const db = getFirestore(app, firebaseConfig.firestoreDatabaseId);

async function run() {
  console.log("Clearing contests...");
  const snapshot = await getDocs(collection(db, "contests"));
  const batch1 = writeBatch(db);
  snapshot.forEach(docSnap => {
    batch1.delete(docSnap.ref);
  });
  await batch1.commit();
  console.log("Cleared.");

  console.log("Importing from public/sample_database.csv...");
  const csvText = fs.readFileSync("./public/sample_database.csv", "utf8");
  const results = Papa.parse(csvText, { header: true, skipEmptyLines: true });
  const data = results.data;
  
  const IMAGE_BASE_URL = 'https://fupc.photo/PicsDB/PicsDB4Search';
  const getImageUrl = (photo) => {
    if (!photo.Published || !photo.PicFileName) return "";
    const year = photo.Published.substring(0, 4);
    return `${IMAGE_BASE_URL}/${year}/${photo.Published}/${photo.PicFileName}`;
  };

  const batch2 = writeBatch(db);
  for (const row of data) {
    const docRef = doc(collection(db, "contests"));
    row.imageUrl = getImageUrl(row);
    // Explicitly copy Winner to WinnerInfo if that helps the ui, though UI already does: WinnerInfo: data.Winner || data.WinnerInfo
    // It's already fine.
    batch2.set(docRef, row);
  }
  await batch2.commit();
  console.log("Import complete. Row count: " + data.length);
  process.exit(0);
}
run();

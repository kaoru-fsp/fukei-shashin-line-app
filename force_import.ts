import { db } from "./src/firebase";
import { collection, getDocs, writeBatch, doc } from "firebase/firestore";
import fs from "fs";
import Papa from "papaparse";

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
  const data = Object.values(results.data);
  console.log(data.slice(0, 2));
  
  const IMAGE_BASE_URL = 'https://fupc.photo/PicsDB/PicsDB4Search';
  const getImageUrl = (photo: any) => {
    if (!photo.Published || !photo.PicFileName) return "";
    const year = photo.Published.substring(0, 4);
    return `${IMAGE_BASE_URL}/${year}/${photo.Published}/${photo.PicFileName}`;
  };

  const batch2 = writeBatch(db);
  for (const row of data) {
    if (typeof row === 'object' && row !== null && 'Title' in row) {
      const docRef = doc(collection(db, "contests"));
      const docData: any = { ...row };
      docData.imageUrl = getImageUrl(docData);
      docData.importedAt = new Date().toISOString();
      
      // Remove any parsed extra that might mess up mapping
      if ('__parsed_extra' in docData) {
        delete docData.__parsed_extra;
      }
      
      batch2.set(docRef, docData);
    }
  }
  await batch2.commit();
  console.log("Import complete. Row count: " + data.length);
  process.exit(0);
}
run();

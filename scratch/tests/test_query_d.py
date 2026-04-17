from db import fetch_data
try:
    res = fetch_data("SELECT TOP 1 LSM010.FolID, LSM007.FolName, COUNT(LSM010.AccNo) AS TotalContracts FROM LSM010 INNER JOIN LSM007 ON LSM007.FolID = LSM010.FolID WHERE LSM010.Stat2 = 'D' GROUP BY LSM010.FolID, LSM007.FolName ORDER BY TotalContracts DESC")
    print('DB RESULT:', res)
except Exception as e:
    print('DB ERROR:', e)

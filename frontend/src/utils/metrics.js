const specialWords = {
  f1: 'F1',
  rmse: 'RMSE',
  mae: 'MAE',
  mse: 'MSE',
  fid: 'FID',
  oks: 'OKS',
  pck: 'PCK',
  snr: 'SNR',
  ssim: 'SSIM',
  psnr: 'PSNR',
  mrr: 'MRR',
  ndcg: 'NDCG',
  map: 'mAP',
  iou: 'IoU',
  chrf: 'chrF',
  bleu: 'BLEU',
  rouge: 'ROUGE',
  meteor: 'METEOR',
  ter: 'TER',
  auc: 'AUC',
  roc: 'ROC',
  mape: 'MAPE',
  ae: 'AE',
  bertscore: 'BERTScore',
  is: 'IS',
  lpips: 'LPIPS',
  niqe: 'NIQE',
  lsd: 'LSD',
  nisqa: 'NISQA',
  pesq: 'PESQ',
  sdr: 'SDR',
  si: 'SI',
};

export const formatMetricName = (name) => {
  if (!name) return '';

  let formatted = name.replace(/_/g, ' ');

  if (formatted.toLowerCase() === 'map 50 95') {
    return 'mAP 50-95';
  }

  return formatted
    .split(' ')
    .map(word => {
      const lower = word.toLowerCase();
      if (specialWords[lower] !== undefined) {
        return specialWords[lower];
      }
      return word.charAt(0).toUpperCase() + word.slice(1);
    })
    .join(' ');
};

%% Figure 3 (Main Plan): Mean trend over normalized dialogue progress (NO heterogeneity shown)
% - Handles varying total rounds per user by normalizing progress to [0, 1]
% - Bins progress into K bins (e.g., 20 bins)
% - For each benchmark, averages across users within each bin
% - Plots ONLY 3 mean curves + 95% CI (no per-user lines)
%
% Prerequisite: run the simulator first (or load your real data into the same format)
% This code expects: sim_proactivity.mat contains T, benchNames, nUsers, nBench
% T columns: user, bench, global_round, score

clear; clc;
load('sim_proactivity.mat', 'T', 'benchNames', 'nUsers', 'nBench');

% ---------------- Style (consistent with your previous figures) ----------------
fontName      = 'Helvetica';
axFontSize    = 16;
labelFontSize = 17.6;
legFontSize   = 16;

cBlue   = [0.0353, 0.5176, 0.8902];
cRed  = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
colors = [cRed; cBlue;  cOrange];   % 3 benchmarks

% ---------------- Parameters ----------------
K = 40;                                % number of progress bins (try 10/20/25)
x = (1:K) / K * 100;                         % bin centers in (0,1]
z = 1.96;                               % ~95% CI

% Smoothing configuration
smoothMethod = 'movmean';     % 'movmean' or 'gaussian'
smoothWindow = 5;             % try 3, 5, 7 (must be <= K)

% ---------------- Compute binned means per user (then average across users) ----------------
% B(u,b,k) = mean score for user u, benchmark b, in progress bin k
B = NaN(nUsers, nBench, K);

for u = 1:nUsers
    for b = 1:nBench
        sel = (T.user == u) & (T.bench == b);
        if ~any(sel), continue; end

        scores = T.score(sel);
        g      = T.global_round(sel);

        % Normalize progress within this user & benchmark to [0, 1]
        gmax = max(g);
        if gmax <= 1
            prog = zeros(size(g));
        else
            prog = (g - 1) / (gmax - 1);
        end

        % Assign each round into one of K bins (1..K)
        binIdx = min(K, max(1, floor(prog * K) + 1));

        % Bin-wise average for this user & benchmark
        for k = 1:K
            s = scores(binIdx == k);
            if ~isempty(s)
                B(u,b,k) = mean(s);
            end
        end
    end
end

% Aggregate across users: mean and 95% CI for each benchmark and bin
mu   = squeeze(mean(B, 1, 'omitnan'));               % nBench x K
sd   = squeeze(std(B,  0, 1, 'omitnan'));            % nBench x K
nEff = squeeze(sum(~isnan(B), 1));                   % nBench x K
se   = sd ./ sqrt(max(nEff, 1));                     % nBench x K
ci95 = z * se;

mu_sm = zeros(size(mu));
se_sm = zeros(size(se));
for b = 1:nBench
    mu_sm(b,:) = smoothdata(mu(b,:), 2, smoothMethod, smoothWindow, 'omitnan');
    se_sm(b,:) = smoothdata(se(b,:), 2, smoothMethod, smoothWindow, 'omitnan');
end
ci95_sm = z * se_sm;

% ---------------- Plot (ONLY 3 curves + CI; no user lines) ----------------
fig = figure('Color','w','Position',[100 100 1000 520]);
ax  = axes(fig); hold(ax, 'on');

for b = 1:nBench
    y  = mu_sm(b,:);
    lo = y - ci95_sm(b,:);
    hi = y + ci95_sm(b,:);

    % CI band (semi-transparent) - does not show heterogeneity, only uncertainty of mean
    hBand = fill(ax, [x, fliplr(x)], [lo, fliplr(hi)], colors(b,:), ...
        'FaceAlpha', 0.18, 'EdgeColor', 'none');
    set(hBand, 'HandleVisibility', 'off');

    % Mean curve
    hLine(b) = plot(ax, x, y, '-o', 'LineWidth', 3, 'MarkerSize', 5, 'Color', colors(b,:));

end

% Axes formatting
xlim(ax, [0 100]);
ylim(ax, [0 2])
xticks(ax, 0:20:100);
xticklabels(ax, compose('%d%%', 0:20:100));  % show 0%, 20%, ..., 100%
xticks(ax, 0:20:100);
yticks(ax, 0:1:2)

xlabel(ax, 'Dialogue Progress', 'FontName', fontName, ...
    'FontSize', labelFontSize, 'FontWeight', 'bold');
ylabel(ax, 'Mean Proactivity Score', 'FontName', fontName, ...
    'FontSize', labelFontSize, 'FontWeight', 'bold');

set(ax, 'FontName', fontName, 'FontSize', axFontSize, ...
    'FontWeight', 'bold', 'LineWidth', 1);
grid(ax, 'on');
box(ax, 'off');

leg = legend(ax, hLine, benchNames, ...
    'Orientation','horizontal', ...
    'NumColumns', 3, ...
    'Location','north');   % or 'southoutside'

set(leg, 'Box','on', 'FontName',fontName, 'FontSize',legFontSize, 'FontWeight','bold');

% Optional export
% exportgraphics(fig, 'trend_normalized_progress.png', 'Resolution', 300);
% exportgraphics(fig, 'trend_normalized_progress.pdf', 'ContentType', 'vector');

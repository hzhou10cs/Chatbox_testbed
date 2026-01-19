%% Figure 1 (Revised Main Plot): Boxplot of per-user mean proactivity score across benchmarks
% Goal:
%   Show distribution (across users) of mean proactivity score for each benchmark.
% X-axis: 3 benchmarks
% Y-axis: proactivity score (0/1/2, averaged -> continuous in [0,2])
%
% Data assumption:
%   sim_proactivity.mat contains:
%     - T: table with columns user, bench, score
%     - benchNames, nUsers, nBench

clear; clc;
load('sim_proactivity.mat', 'T', 'benchNames', 'nUsers', 'nBench');

% ---------------- Style (consistent with your previous figures) ----------------
fontName      = 'Helvetica';
axFontSize    = 16;
labelFontSize = 17.6;

cBlue   = [0.0353, 0.5176, 0.8902];
cRed  = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
colors = [cRed; cBlue;  cOrange]; 

% ---------------- Compute per-user mean score for each benchmark ----------------
M = NaN(nUsers, nBench);
for u = 1:nUsers
    for b = 1:nBench
        sel = (T.user==u) & (T.bench==b);
        M(u,b) = mean(T.score(sel));
    end
end

% Reshape for boxplot: one vector of values + group labels
vals = M(:);
grp  = repelem((1:nBench)', nUsers, 1);  % groups: 1..nBench, each repeated nUsers times

% ---------------- Plot: boxplot + jittered points (optional but recommended) ----------------
fig = figure('Color','w', 'Position',[100 100 600 500]);
ax  = axes(fig); hold(ax, 'on');

% Boxplot
boxplot(ax, vals, grp, ...
    'Labels', benchNames, ...
    'Symbol', '', ...                    % hide default outlier markers (cleaner)
    'Whisker', 1.5, ...
    'Widths', 0.55);

% Make boxplot lines bold and consistent
set(findobj(ax,'Type','Line'), 'LineWidth', 2);

% Color the boxes (MATLAB boxplot uses patches not by default; we create patches)
hBox = findobj(ax, 'Tag', 'Box');  % one per group, returned in reverse order
for b = 1:nBench
    % hBox is reverse-ordered; map accordingly
    hb = hBox(nBench - b + 1);
    xd = get(hb, 'XData');
    yd = get(hb, 'YData');
    patch('XData', xd, 'YData', yd, ...
          'FaceColor', colors(b,:), 'FaceAlpha', 0.18, ...
          'EdgeColor', colors(b,:), 'LineWidth', 2);
end

% Optional: overlay per-user points with slight jitter (helps interpret distribution)
% Comment out if you want pure boxplots only.
jitterAmount = 0.10;
for b = 1:nBench
    x0 = b;
    y  = M(:,b);
    xj = x0 + (rand(size(y))-0.5) * 2 * jitterAmount;
    plot(ax, xj, y, 'o', 'MarkerSize', 6, 'LineWidth', 1.5, 'Color', colors(b,:));
end

% ---------------- Axes formatting ----------------
ylim(ax, [0 2]);
yticks(ax, 0:0.5:2);

ylabel(ax, 'Proactivity Score', ...
    'FontName', fontName, 'FontSize', labelFontSize, 'FontWeight', 'bold');

set(ax, 'FontName', fontName, 'FontSize', axFontSize, ...
    'FontWeight', 'bold', 'LineWidth', 1);
grid(ax, 'on');
box(ax, 'off');

% Optional: tighten x-limits slightly for aesthetics
xlim(ax, [0.5, nBench+0.5]);

% Optional export
% exportgraphics(fig, 'main_boxplot_user_mean.png', 'Resolution', 300);
% exportgraphics(fig, 'main_boxplot_user_mean.pdf', 'ContentType', 'vector');

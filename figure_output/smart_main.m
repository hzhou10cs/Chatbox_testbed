%% (1) Main Fig 1: Boxplot of per-user overall SMART by benchmark
clear; clc;
load('sim_smart.mat', 'scores','benchNames','nUsers','nBench','colors');

% Style
fontName = 'Helvetica';
axFontSize = 16;
labelFontSize = 17.6;

% Compute per-goal overall then per-user overall
% overallGoal(u,b,d,s) = mean over dims
overallGoal = mean(scores, 5);                    % (u,b,d,s)
userOverall = squeeze(mean(overallGoal, [3 4]));  % (u,b)

vals = userOverall(:);
grp  = repelem((1:nBench)', nUsers, 1);

fig = figure('Color','w', 'Position',[100 100 600 500]);
ax  = axes(fig); hold(ax,'on');

boxplot(ax, vals, grp, ...
    'Labels', benchNames, ...
    'Symbol', '', ...
    'Whisker', 1.5, ...
    'Widths', 0.55);

% Bold lines
set(findobj(ax,'Type','Line'), 'LineWidth', 2);

% Color boxes using patches
hBox = findobj(ax, 'Tag', 'Box'); % reverse order
for b = 1:nBench
    hb = hBox(nBench - b + 1);
    xd = get(hb, 'XData'); yd = get(hb, 'YData');
    patch('XData', xd, 'YData', yd, ...
        'FaceColor', colors(b,:), 'FaceAlpha', 0.18, ...
        'EdgeColor', colors(b,:), 'LineWidth', 2);
end

% Overlay user points with jitter
jitter = 0.10;
for b = 1:nBench
    y = userOverall(:,b);
    x = b + (rand(size(y))-0.5)*2*jitter;
    plot(ax, x, y, 'o', 'MarkerSize', 6, 'LineWidth', 1.5, 'Color', colors(b,:));
end

ylim(ax, [0 5]);
yticks(ax, 0:1:5);

ylabel(ax, 'Overall SMART Score', 'FontName',fontName, 'FontSize',labelFontSize, 'FontWeight','bold');

set(ax, 'FontName',fontName, 'FontSize',axFontSize, 'FontWeight','bold', 'LineWidth',1);
grid(ax, 'on');
box(ax, 'off');
xlim(ax, [0.5 nBench+0.5]);
